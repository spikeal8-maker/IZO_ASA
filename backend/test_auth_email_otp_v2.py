"""Email OTP auth v2 tests (Phase 8).

No real email is ever sent (mock outbox). OTP is obtained via the dev-only
debug_code path (EMAIL_OTP_DEBUG_RETURN_CODE) — never by reading a stored raw OTP
(none is stored). All tests use a TEMPORARY SQLite DB via monkeypatching main.DB_PATH.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from test_support.browser_client import BrowserTestClient


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "email_otp_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "APP_ENV", "development")
    monkeypatch.setattr(main, "SESSION_HMAC_SECRET", "unit-test-session-secret")
    monkeypatch.setattr(main, "EMAIL_OTP_DEBUG_RETURN_CODE", True)  # dev only
    monkeypatch.setattr(main, "EMAIL_OTP_TTL_SECONDS", 300)
    monkeypatch.setattr(main, "EMAIL_OTP_MAX_ATTEMPTS", 5)
    main._mock_email_outbox.clear()
    main.init_db()
    yield db_file
    main._mock_email_outbox.clear()


def count(table, where="", params=()):
    with main.db() as conn:
        return conn.execute(f"SELECT COUNT(*) AS c FROM {table} {where}", params).fetchone()["c"]


def request_code(client, email="User@Example.com", **body):
    payload = {"platform": "web_desktop", "email": email}
    payload.update(body)
    return client.post("/api/auth/email/request-code-v2", json=payload)


def verify_code(client, challenge_id, code, **body):
    payload = {"platform": "web_desktop", "challenge_id": challenge_id, "code": code}
    payload.update(body)
    return client.post("/api/auth/email/verify-code-v2", json=payload)


# 1, 2
def test_request_code_creates_challenge_with_hash_only(temp_db):
    with TestClient(main.app) as client:
        r = request_code(client, "person@example.com")
    assert r.status_code == 200
    code = r.json()["debug_code"]
    with main.db() as conn:
        row = conn.execute("SELECT * FROM auth_otp_challenges").fetchone()
    assert row is not None
    assert row["code_hash"] == main.hash_otp(code)
    blob = " ".join(str(v) for v in tuple(row))
    assert code not in blob  # raw OTP never stored


# 3
def test_request_code_normalizes_email(temp_db):
    with TestClient(main.app) as client:
        request_code(client, "  PaDDed@Example.COM ")
    with main.db() as conn:
        dest = conn.execute("SELECT destination FROM auth_otp_challenges").fetchone()["destination"]
    assert dest == "padded@example.com"


# 4
def test_request_code_rejects_invalid_email(temp_db):
    with TestClient(main.app) as client:
        for bad in ["", "   ", "no-at-symbol", "a@b", "a@b@c.com"]:
            r = request_code(client, bad)
            assert r.status_code == 400, bad


# 5
def test_response_shape_same_regardless_of_user_existence(temp_db, monkeypatch):
    monkeypatch.setattr(main, "EMAIL_OTP_REQUEST_COOLDOWN_SECONDS", 0)  # not testing rate limits here
    # Browser flow: verify stores the session cookie, later request_code posts
    # are unsafe requests from the same browser (AUTH-LEGACY-001B).
    with BrowserTestClient(main.app) as client:
        # first login creates the user
        r1 = request_code(client, "exists@example.com")
        code = r1.json()["debug_code"]
        verify_code(client, r1.json()["challenge_id"], code)
        # second request for the SAME (now existing) email
        r2 = request_code(client, "exists@example.com")
        # and a brand-new email
        r3 = request_code(client, "brandnew@example.com")
    assert set(r2.json().keys()) == set(r3.json().keys())
    assert "challenge_id" in r2.json() and "expires_in_seconds" in r2.json()


# 6
def test_login_started_event_without_otp(temp_db):
    with TestClient(main.app) as client:
        r = request_code(client, "evt@example.com")
        code = r.json()["debug_code"]
    assert count("event_logs", "WHERE event_name='login_started'") == 1
    with main.db() as conn:
        for row in conn.execute("SELECT * FROM event_logs WHERE event_name='login_started'"):
            assert code not in " ".join(str(v) for v in tuple(row))


# 7
def test_no_real_email_sent_in_dev(temp_db):
    with TestClient(main.app) as client:
        request_code(client, "mock@example.com")
    assert len(main._mock_email_outbox) == 1
    entry = main._mock_email_outbox[0]
    assert entry["to"] == "mock@example.com"
    assert "code" not in entry  # mock never carries the OTP


# 8, 9, 10
def test_verify_creates_user_identity_and_session(temp_db):
    with TestClient(main.app) as client:
        r = request_code(client, "new@example.com")
        code = r.json()["debug_code"]
        v = verify_code(client, r.json()["challenge_id"], code)
    assert v.status_code == 200, v.text
    b = v.json()
    assert b["session_token"] and b["refresh_token"]
    assert b["internal_user_id"] and b["legacy_user_id"]
    assert b["legacy_user_id"].startswith("web_")
    with main.db() as conn:
        ident = conn.execute("SELECT * FROM auth_identities WHERE provider='web_email' AND provider_user_id='new@example.com'").fetchone()
        assert ident is not None and ident["verified_at"] is not None
        sess = conn.execute("SELECT * FROM auth_sessions").fetchone()
    assert sess["session_token_hash"] == main.hash_token(b["session_token"])
    blob = " ".join(str(v2) for v2 in tuple(sess))
    assert b["session_token"] not in blob and b["refresh_token"] not in blob


# 11, 12
def test_repeated_login_same_email_reuses_internal_id(temp_db, monkeypatch):
    monkeypatch.setattr(main, "EMAIL_OTP_REQUEST_COOLDOWN_SECONDS", 0)  # not testing rate limits here
    # Browser flow: verify stores the session cookie, the second login is an
    # unsafe request from the same browser (AUTH-LEGACY-001B).
    with BrowserTestClient(main.app) as client:
        r1 = request_code(client, "same@example.com")
        b1 = verify_code(client, r1.json()["challenge_id"], r1.json()["debug_code"]).json()
        r2 = request_code(client, "same@example.com")
        b2 = verify_code(client, r2.json()["challenge_id"], r2.json()["debug_code"]).json()
    assert b1["internal_user_id"] == b2["internal_user_id"]
    assert count("auth_identities", "WHERE provider='web_email' AND provider_user_id='same@example.com'") == 1


# 13, 14, 15
def test_invalid_code_increments_attempts_and_logs(temp_db):
    with TestClient(main.app) as client:
        r = request_code(client, "wrong@example.com")
        cid = r.json()["challenge_id"]
        bad = verify_code(client, cid, "000000" if r.json()["debug_code"] != "000000" else "111111")
    assert bad.status_code == 401
    with main.db() as conn:
        attempts = conn.execute("SELECT attempts_count FROM auth_otp_challenges WHERE id=?", (cid,)).fetchone()["attempts_count"]
    assert attempts == 1
    assert count("auth_login_attempts", "WHERE provider='web_email' AND success=0") == 1
    assert count("security_events", "WHERE event_type='otp_failed'") == 1


# 16
def test_expired_code_returns_401(temp_db):
    with TestClient(main.app) as client:
        r = request_code(client, "expired@example.com")
        cid = r.json()["challenge_id"]
        code = r.json()["debug_code"]
        with main.db() as conn:
            conn.execute("UPDATE auth_otp_challenges SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (cid,))
        v = verify_code(client, cid, code)
    assert v.status_code == 401
    assert count("security_events", "WHERE event_type='otp_expired'") == 1


# 17
def test_consumed_code_reuse_returns_401(temp_db):
    # Browser flow: the first verify stores the session cookie, the second
    # verify is an unsafe request from the same browser (AUTH-LEGACY-001B).
    with BrowserTestClient(main.app) as client:
        r = request_code(client, "reuse@example.com")
        cid, code = r.json()["challenge_id"], r.json()["debug_code"]
        first = verify_code(client, cid, code)
        assert first.status_code == 200
        second = verify_code(client, cid, code)
    assert second.status_code == 401
    assert count("security_events", "WHERE event_type='otp_consumed'") == 1


# 18
def test_max_attempts_returns_429(temp_db):
    with TestClient(main.app) as client:
        r = request_code(client, "brute@example.com")
        cid, code = r.json()["challenge_id"], r.json()["debug_code"]
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            verify_code(client, cid, wrong)
        blocked = verify_code(client, cid, wrong)
    assert blocked.status_code == 429
    assert count("security_events", "WHERE event_type='otp_max_attempts'") == 1


# 19
def test_missing_challenge_returns_401(temp_db):
    with TestClient(main.app) as client:
        v = verify_code(client, "does-not-exist", "123456")
    assert v.status_code == 401


# 20
def test_frontend_user_id_in_body_ignored(temp_db):
    with TestClient(main.app) as client:
        r = request_code(client, "ignore@example.com")
        b = verify_code(client, r.json()["challenge_id"], r.json()["debug_code"],
                        user_id="admin", internal_user_id="iuid-injected", legacy_user_id="web_admin").json()
    assert b["internal_user_id"] != "iuid-injected"
    assert b["legacy_user_id"] != "web_admin"


# 21
def test_x_onenode_user_header_ignored(temp_db):
    with TestClient(main.app) as client:
        r = client.post("/api/auth/email/request-code-v2",
                        json={"platform": "web_desktop", "email": "hdr@example.com"},
                        headers={"X-OneNode-User": "admin"})
        cid, code = r.json()["challenge_id"], r.json()["debug_code"]
        v = client.post("/api/auth/email/verify-code-v2",
                        json={"platform": "web_desktop", "challenge_id": cid, "code": code},
                        headers={"X-OneNode-User": "admin"})
    assert v.status_code == 200
    assert v.json()["legacy_user_id"] != "admin"


# 22
def test_onenode_user_cookie_ignored(temp_db):
    with TestClient(main.app) as client:
        client.cookies.set("onenode_user", "admin")
        r = request_code(client, "cookie@example.com")
        v = verify_code(client, r.json()["challenge_id"], r.json()["debug_code"])
    assert v.status_code == 200
    assert v.json()["legacy_user_id"] != "admin"


# 23
def test_raw_otp_not_in_any_log_table(temp_db):
    with TestClient(main.app) as client:
        r = request_code(client, "secret@example.com")
        cid, code = r.json()["challenge_id"], r.json()["debug_code"]
        verify_code(client, cid, "999999" if code != "999999" else "888888")  # a failure path too
        verify_code(client, cid, code)
    with main.db() as conn:
        for table in ("auth_otp_challenges", "event_logs", "security_events", "auth_login_attempts"):
            for row in conn.execute(f"SELECT * FROM {table}").fetchall():
                assert code not in " ".join(str(v) for v in tuple(row)), table


# 24
def test_raw_tokens_not_stored(temp_db):
    with TestClient(main.app) as client:
        r = request_code(client, "tok@example.com")
        b = verify_code(client, r.json()["challenge_id"], r.json()["debug_code"]).json()
    with main.db() as conn:
        row = conn.execute("SELECT session_token_hash, refresh_token_hash FROM auth_sessions").fetchone()
    assert row["session_token_hash"] != b["session_token"]
    assert row["refresh_token_hash"] != b["refresh_token"]


# 25
def test_event_log_login_succeeded(temp_db):
    with TestClient(main.app) as client:
        r = request_code(client, "ok@example.com")
        verify_code(client, r.json()["challenge_id"], r.json()["debug_code"])
    assert count("event_logs", "WHERE event_name='login_succeeded'") == 1


# 26
def test_event_log_login_failed(temp_db):
    with TestClient(main.app) as client:
        r = request_code(client, "fail@example.com")
        code = r.json()["debug_code"]
        verify_code(client, r.json()["challenge_id"], "000000" if code != "000000" else "111111")
    assert count("event_logs", "WHERE event_name='login_failed'") == 1


# 27
def test_device_installation_linked(temp_db):
    with TestClient(main.app) as client:
        r = request_code(client, "dev@example.com", installation_id="inst-eml-1", anonymous_id="anon-1")
        b = verify_code(client, r.json()["challenge_id"], r.json()["debug_code"],
                        installation_id="inst-eml-1", anonymous_id="anon-1").json()
    with main.db() as conn:
        row = conn.execute("SELECT internal_user_id FROM device_installations WHERE installation_id='inst-eml-1'").fetchone()
    assert row["internal_user_id"] == b["internal_user_id"]


# 29
def test_production_debug_return_code_fails_config(temp_db, monkeypatch):
    monkeypatch.setattr(main, "APP_ENV", "production")
    monkeypatch.setattr(main, "EMAIL_OTP_DEBUG_RETURN_CODE", True)
    # This test exercises OTP fail-closed behaviour with a temporary database;
    # DB Guard production-path validation has its own dedicated test module.
    monkeypatch.setattr(main, "db_guard_preflight", lambda: None)
    monkeypatch.setattr(main, "enforce_db_guard_after_migrations", lambda: None)
    with pytest.raises(RuntimeError):
        main.validate_email_otp_config()
    with TestClient(main.app) as client:
        r = request_code(client, "prod@example.com")
    assert r.status_code == 503
    assert count("auth_otp_challenges") == 0  # no challenge created


# 30
def test_production_without_provider_fails_safely(temp_db, monkeypatch):
    monkeypatch.setattr(main, "APP_ENV", "production")
    monkeypatch.setattr(main, "EMAIL_OTP_DEBUG_RETURN_CODE", False)
    monkeypatch.setattr(main, "EMAIL_PROVIDER", "")
    # Keep this focused on OTP provider validation, not DB Guard configuration.
    monkeypatch.setattr(main, "db_guard_preflight", lambda: None)
    monkeypatch.setattr(main, "enforce_db_guard_after_migrations", lambda: None)
    with pytest.raises(RuntimeError):
        main.validate_email_otp_config()
    main._mock_email_outbox.clear()
    with TestClient(main.app) as client:
        r = request_code(client, "prod2@example.com")
    assert r.status_code == 503
    assert count("auth_otp_challenges") == 0
    assert len(main._mock_email_outbox) == 0  # no fake email sent
