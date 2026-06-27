"""Email OTP rate limiting / cooldown / cleanup tests (Phase 8.1).

No real email is sent (mock outbox). All tests use a TEMPORARY SQLite DB via
monkeypatching main.DB_PATH; backend/onenode.sqlite3 is never touched.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "email_rl_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "APP_ENV", "development")
    monkeypatch.setattr(main, "EMAIL_OTP_DEBUG_RETURN_CODE", True)
    monkeypatch.setattr(main, "EMAIL_OTP_TTL_SECONDS", 300)
    # generous defaults; individual tests tighten what they exercise
    monkeypatch.setattr(main, "EMAIL_OTP_REQUEST_COOLDOWN_SECONDS", 60)
    monkeypatch.setattr(main, "EMAIL_OTP_MAX_REQUESTS_PER_EMAIL_WINDOW", 5)
    monkeypatch.setattr(main, "EMAIL_OTP_EMAIL_WINDOW_SECONDS", 900)
    monkeypatch.setattr(main, "EMAIL_OTP_MAX_REQUESTS_PER_IP_WINDOW", 20)
    monkeypatch.setattr(main, "EMAIL_OTP_IP_WINDOW_SECONDS", 900)
    monkeypatch.setattr(main, "EMAIL_OTP_MAX_ACTIVE_CHALLENGES_PER_EMAIL", 3)
    monkeypatch.setattr(main, "EMAIL_OTP_CLEANUP_EXPIRED_AFTER_SECONDS", 86400)
    main._mock_email_outbox.clear()
    main.init_db()
    yield db_file
    main._mock_email_outbox.clear()


def count(table, where="", params=()):
    with main.db() as conn:
        return conn.execute(f"SELECT COUNT(*) AS c FROM {table} {where}", params).fetchone()["c"]


def request_code(client, email, **body):
    payload = {"platform": "web_desktop", "email": email}
    payload.update(body)
    return client.post("/api/auth/email/request-code-v2", json=payload)


# 1
def test_first_request_allowed(temp_db):
    with TestClient(main.app) as client:
        r = request_code(client, "first@example.com")
    assert r.status_code == 200
    assert "challenge_id" in r.json()


# 2,3,4,5,6
def test_cooldown_blocks_second_request(temp_db):
    with TestClient(main.app) as client:
        r1 = request_code(client, "cool@example.com")
        assert r1.status_code == 200
        before_challenges = count("auth_otp_challenges")
        before_outbox = len(main._mock_email_outbox)
        r2 = request_code(client, "cool@example.com")
    assert r2.status_code == 429
    assert r2.json() == {"detail": "Too many requests"}
    assert count("auth_otp_challenges") == before_challenges          # 3: no new challenge
    assert len(main._mock_email_outbox) == before_outbox              # 4: no email sent
    assert count("security_events", "WHERE event_type='otp_request_rate_limited'") == 1  # 5
    assert count("event_logs", "WHERE event_name='login_rate_limited'") == 1             # 6


# 7
def test_email_window_limit(temp_db, monkeypatch):
    monkeypatch.setattr(main, "EMAIL_OTP_REQUEST_COOLDOWN_SECONDS", 0)  # disable cooldown
    monkeypatch.setattr(main, "EMAIL_OTP_MAX_REQUESTS_PER_EMAIL_WINDOW", 3)
    monkeypatch.setattr(main, "EMAIL_OTP_MAX_ACTIVE_CHALLENGES_PER_EMAIL", 99)
    with TestClient(main.app) as client:
        for _ in range(3):
            assert request_code(client, "win@example.com").status_code == 200
        blocked = request_code(client, "win@example.com")
    assert blocked.status_code == 429


# 8
def test_ip_window_limit(temp_db, monkeypatch):
    monkeypatch.setattr(main, "EMAIL_OTP_MAX_REQUESTS_PER_IP_WINDOW", 3)
    with TestClient(main.app) as client:
        # distinct emails to avoid cooldown/email-window; same IP (testclient)
        for i in range(3):
            assert request_code(client, f"ip{i}@example.com").status_code == 200
        blocked = request_code(client, "ip-final@example.com")
    assert blocked.status_code == 429


# 9
def test_max_active_challenges(temp_db, monkeypatch):
    monkeypatch.setattr(main, "EMAIL_OTP_REQUEST_COOLDOWN_SECONDS", 0)
    monkeypatch.setattr(main, "EMAIL_OTP_MAX_REQUESTS_PER_EMAIL_WINDOW", 99)
    monkeypatch.setattr(main, "EMAIL_OTP_MAX_REQUESTS_PER_IP_WINDOW", 99)
    monkeypatch.setattr(main, "EMAIL_OTP_MAX_ACTIVE_CHALLENGES_PER_EMAIL", 3)
    with TestClient(main.app) as client:
        for _ in range(3):
            assert request_code(client, "active@example.com").status_code == 200
        blocked = request_code(client, "active@example.com")
    assert blocked.status_code == 429


# 10
def test_rate_limit_does_not_reveal_user_existence(temp_db, monkeypatch):
    # existing user (verify once) vs brand-new email should both 429 identically
    monkeypatch.setattr(main, "EMAIL_OTP_REQUEST_COOLDOWN_SECONDS", 0)
    monkeypatch.setattr(main, "EMAIL_OTP_MAX_ACTIVE_CHALLENGES_PER_EMAIL", 1)
    monkeypatch.setattr(main, "EMAIL_OTP_MAX_REQUESTS_PER_EMAIL_WINDOW", 99)
    monkeypatch.setattr(main, "EMAIL_OTP_MAX_REQUESTS_PER_IP_WINDOW", 99)
    with TestClient(main.app) as client:
        # create an account for existing@
        r = request_code(client, "existing@example.com")
        main_code = r.json()["debug_code"]
        client.post("/api/auth/email/verify-code-v2",
                    json={"platform": "web_desktop", "challenge_id": r.json()["challenge_id"], "code": main_code})
        # now drive both to the active-challenge limit
        request_code(client, "existing@example.com")  # 1 active -> next blocked
        blocked_existing = request_code(client, "existing@example.com")
        request_code(client, "fresh@example.com")
        blocked_fresh = request_code(client, "fresh@example.com")
    assert blocked_existing.status_code == blocked_fresh.status_code == 429
    assert blocked_existing.json() == blocked_fresh.json() == {"detail": "Too many requests"}


# 11, 12
def test_rate_limit_does_not_store_or_log_raw_otp(temp_db):
    with TestClient(main.app) as client:
        r1 = request_code(client, "raw@example.com")
        code = r1.json()["debug_code"]
        request_code(client, "raw@example.com")  # cooldown 429
    # only one challenge exists; the 429 created none
    assert count("auth_otp_challenges") == 1
    with main.db() as conn:
        for table in ("security_events", "event_logs", "auth_login_attempts"):
            for row in conn.execute(f"SELECT * FROM {table}").fetchall():
                assert code not in " ".join(str(v) for v in tuple(row)), table


# 13, 14, 15
def test_cleanup_removes_stale_keeps_active(temp_db):
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    with main.db() as conn:
        # old expired
        conn.execute(
            "INSERT INTO auth_otp_challenges (id, channel, destination, code_hash, purpose, attempts_count, max_attempts, expires_at, consumed_at, created_at) "
            "VALUES ('old-exp','email','a@x.com','h','login',0,5, ?, NULL, ?)",
            ((datetime.now(timezone.utc) - timedelta(days=2)).isoformat(), old),
        )
        # old consumed
        conn.execute(
            "INSERT INTO auth_otp_challenges (id, channel, destination, code_hash, purpose, attempts_count, max_attempts, expires_at, consumed_at, created_at) "
            "VALUES ('old-con','email','b@x.com','h','login',0,5, ?, ?, ?)",
            ((datetime.now(timezone.utc) + timedelta(days=1)).isoformat(), old, old),
        )
        # active unexpired recent
        conn.execute(
            "INSERT INTO auth_otp_challenges (id, channel, destination, code_hash, purpose, attempts_count, max_attempts, expires_at, consumed_at, created_at) "
            "VALUES ('active','email','c@x.com','h','login',0,5, ?, NULL, ?)",
            ((datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(), datetime.now(timezone.utc).isoformat()),
        )
    removed = main.cleanup_expired_otp_challenges()
    assert removed == 2
    assert count("auth_otp_challenges", "WHERE id='old-exp'") == 0   # 13
    assert count("auth_otp_challenges", "WHERE id='old-con'") == 0   # 14
    assert count("auth_otp_challenges", "WHERE id='active'") == 1    # 15
    # idempotent
    assert main.cleanup_expired_otp_challenges() == 0


# 16
def test_request_after_cleanup_still_works(temp_db):
    main.cleanup_expired_otp_challenges()
    with TestClient(main.app) as client:
        r = request_code(client, "after-clean@example.com")
    assert r.status_code == 200


# 17
def test_invalid_email_400_and_not_counted(temp_db):
    with TestClient(main.app) as client:
        bad = request_code(client, "not-an-email")
        assert bad.status_code == 400
        assert count("auth_otp_challenges") == 0
        assert count("security_events", "WHERE event_type='otp_request_rate_limited'") == 0
        # a subsequent valid request is unaffected
        ok = request_code(client, "valid@example.com")
    assert ok.status_code == 200


# 19
def test_request_user_id_and_require_admin_unchanged():
    import inspect
    src = inspect.getsource(main.request_user_id) + inspect.getsource(main.require_admin)
    assert "auth_sessions" not in src  # still legacy, untouched by v2 work


# 20
def test_telegram_and_max_v2_endpoints_present():
    routes = {r.path for r in main.app.routes}
    assert "/api/auth/telegram-v2" in routes
    assert "/api/auth/max-v2" in routes
