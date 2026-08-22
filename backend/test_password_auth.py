"""Email+password register/login endpoint tests (Phase 14.5).

Temporary SQLite DB via monkeypatching main.DB_PATH; working DB never touched.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
# Browser-faithful contract: cookie-auth mutations carry an allowlisted Origin
# to pass the CSRF boundary (AUTH-LEGACY-001B). change-password always runs on
# an authenticated (cookie-bearing) client; register/login carry the cookie on
# repeated calls against a shared client.
from test_support.browser_origin import BROWSER_ORIGIN

PW = "S3cret-Password!"


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "password_auth_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "APP_ENV", "development")
    monkeypatch.setattr(main, "SESSION_HMAC_SECRET", "unit-test-session-secret")
    monkeypatch.setattr(main, "EMAIL_PROVIDER", "")
    monkeypatch.setattr(main, "EMAIL_OTP_DEBUG_RETURN_CODE", False)
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    main._mock_email_outbox.clear()
    main.init_db()
    yield db_file
    main._mock_email_outbox.clear()


def count(table, where="", params=()):
    with main.db() as conn:
        return conn.execute(f"SELECT COUNT(*) AS c FROM {table} {where}", params).fetchone()["c"]


def set_cookies(resp):
    return " ".join(resp.headers.get_list("set-cookie")).lower() if hasattr(resp.headers, "get_list") else resp.headers.get("set-cookie", "").lower()


def register(client, email, password=PW, repeat=None):
    return client.post("/api/auth/password/register-v2", json={
        "email": email, "password": password, "password_repeat": repeat if repeat is not None else password,
        "accepted_terms": True, "accepted_privacy": True, "accepted_personal_data": True, "platform": "web_desktop",
    }, headers=BROWSER_ORIGIN)


def login(client, email, password=PW):
    return client.post("/api/auth/password/login-v2", json={"email": email, "password": password, "platform": "web_desktop"}, headers=BROWSER_ORIGIN)


def change_password(client, current_password=PW, new_password="N3w-Secure-Password!"):
    return client.post("/api/auth/password/change-v2", json={
        "current_password": current_password,
        "new_password": new_password,
        "new_password_repeat": new_password,
    }, headers=BROWSER_ORIGIN)


def request_code(client, email):
    return client.post("/api/auth/email/request-code-v2", json={"email": email, "platform": "web_desktop"})


def verify_code(client, challenge_id, code):
    return client.post("/api/auth/email/verify-code-v2", json={"challenge_id": challenge_id, "code": code, "platform": "web_desktop"})


# 1, 2, 3, 4
def test_register_creates_identity_password_consents_cookies(temp_db):
    with TestClient(main.app) as c:
        r = register(c, "user@example.com")
    assert r.status_code == 200 and r.json()["ok"] is True
    iuid = r.json()["internal_user_id"]
    sc = set_cookies(r)
    assert "onenode_session=" in sc and "onenode_refresh=" in sc and "httponly" in sc
    with main.db() as conn:
        ident = conn.execute("SELECT * FROM auth_identities WHERE provider='web_email' AND provider_user_id='user@example.com'").fetchone()
        assert ident is not None
        pw = conn.execute("SELECT password_hash, algorithm FROM auth_passwords WHERE internal_user_id=? AND disabled_at IS NULL", (iuid,)).fetchone()
        assert pw is not None and pw["algorithm"] == "argon2id"
        assert pw["password_hash"].startswith("$argon2id$") and PW not in pw["password_hash"]
    for ct in ("terms", "privacy", "personal_data_processing"):
        assert count("user_consents", "WHERE internal_user_id=? AND consent_type=?", (iuid, ct)) == 1


# 5
def test_register_existing_email_generic_409(temp_db):
    with TestClient(main.app) as c:
        register(c, "dup@example.com")
    with TestClient(main.app) as c2:
        r = register(c2, "dup@example.com")
    assert r.status_code == 409
    assert "уже существует" in r.json()["detail"].lower() or "некоррект" in r.json()["detail"].lower()


def test_register_password_mismatch_400(temp_db):
    with TestClient(main.app) as c:
        r = register(c, "mm@example.com", password=PW, repeat="different-pass")
    assert r.status_code == 400


def test_register_requires_consent(temp_db):
    with TestClient(main.app) as c:
        r = c.post("/api/auth/password/register-v2", json={"email": "nc@example.com", "password": PW, "password_repeat": PW, "accepted_terms": True, "accepted_privacy": False, "accepted_personal_data": True})
    assert r.status_code == 400


# 6
def test_login_correct_sets_cookies(temp_db):
    with TestClient(main.app) as c:
        register(c, "login@example.com")
    with TestClient(main.app) as c2:
        r = login(c2, "login@example.com")
    assert r.status_code == 200 and r.json()["ok"] is True
    sc = set_cookies(r)
    assert "onenode_session=" in sc and "onenode_refresh=" in sc and "httponly" in sc
    # cookie session actually authenticates
    with TestClient(main.app) as c3:
        register(c3, "login2@example.com")
        me = c3.get("/api/me-v2")
        assert me.status_code == 200


# 7, 8, 9
def test_login_wrong_and_unknown_same_generic_401(temp_db):
    with TestClient(main.app) as c:
        register(c, "real@example.com")
    with TestClient(main.app) as c2:
        wrong = login(c2, "real@example.com", password="totally-wrong-pass")
        unknown = login(c2, "ghost@example.com", password=PW)
    assert wrong.status_code == 401 and unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"] == "Неверная почта или пароль."


# 10
def test_banned_user_login_403(temp_db):
    with TestClient(main.app) as c:
        r = register(c, "ban@example.com")
        iuid = r.json()["internal_user_id"]
    with main.db() as conn:
        conn.execute("UPDATE users SET banned=1 WHERE internal_user_id=?", (iuid,))
    with TestClient(main.app) as c2:
        r = login(c2, "ban@example.com")
    assert r.status_code == 403


# 11, 12
def test_failed_login_logs_and_success_event(temp_db):
    with TestClient(main.app) as c:
        register(c, "logs@example.com")
    with TestClient(main.app) as c2:
        login(c2, "logs@example.com", password="bad")
        login(c2, "logs@example.com")
    assert count("auth_login_attempts", "WHERE provider='web_email' AND success=0") >= 1
    assert count("security_events", "WHERE event_type='password_login_failed'") >= 1
    assert count("event_logs", "WHERE event_name='password_login_succeeded'") == 1
    assert count("event_logs", "WHERE event_name='password_register_succeeded'") == 1


# 13, 14
def test_raw_password_and_tokens_not_in_db(temp_db):
    with TestClient(main.app) as c:
        r = register(c, "secrets@example.com")
    body = r.json()
    with main.db() as conn:
        for table in ("auth_passwords", "auth_login_attempts", "security_events", "event_logs", "user_consents", "auth_sessions"):
            for row in conn.execute(f"SELECT * FROM {table}").fetchall():
                blob = " ".join(str(v) for v in tuple(row))
                assert PW not in blob, f"raw password leaked into {table}"
        # session row stores only hashes, no raw token returned to body anyway
        srow = conn.execute("SELECT session_token_hash, refresh_token_hash FROM auth_sessions").fetchone()
    assert "session_token" not in body  # cookie-only response
    assert srow["session_token_hash"] and srow["refresh_token_hash"]


# 15
def test_users_id_unchanged(temp_db):
    with main.db() as conn:
        conn.execute("INSERT INTO users (id, internal_user_id, language, role, created_at, last_login_at) VALUES ('telegram_legacy','iuid-legacy','ru','user','2026-01-01','2026-01-01')")
        before = sorted(r["id"] for r in conn.execute("SELECT id FROM users"))
    with TestClient(main.app) as c:
        register(c, "newuser@example.com")
    with main.db() as conn:
        after = sorted(r["id"] for r in conn.execute("SELECT id FROM users"))
    # legacy id still present and unchanged; new user added with web_ id (not a UUID replacement of existing)
    assert "telegram_legacy" in after
    assert all(i in after for i in before)


def test_register_with_email_provider_login_before_verify_is_blocked(temp_db, monkeypatch):
    monkeypatch.setattr(main, "EMAIL_PROVIDER", "smtp")
    monkeypatch.setattr(main, "EMAIL_OTP_DEBUG_RETURN_CODE", True)
    with TestClient(main.app) as c:
        r = register(c, "pending@example.com")
        assert r.status_code == 200
        assert r.json()["requires_email_verification"] is True
        assert "onenode_session=" not in set_cookies(r)
        blocked = login(c, "pending@example.com")
        assert blocked.status_code == 403
        assert blocked.json() == {
            "detail": "email_verification_required",
            "requires_email_verification": True,
            "email": "pending@example.com",
        }
        assert "onenode_session=" not in set_cookies(blocked)
        me = c.get("/api/me-v2")
    assert me.status_code == 401


def test_register_verify_code_then_me_v2_is_authenticated(temp_db, monkeypatch):
    monkeypatch.setattr(main, "EMAIL_PROVIDER", "smtp")
    monkeypatch.setattr(main, "EMAIL_OTP_DEBUG_RETURN_CODE", True)
    with TestClient(main.app) as c:
        r = register(c, "verify@example.com")
        assert r.status_code == 200
        challenge = request_code(c, "verify@example.com")
        assert challenge.status_code == 200
        verified = verify_code(c, challenge.json()["challenge_id"], challenge.json()["debug_code"])
        assert verified.status_code == 200
        me = c.get("/api/me-v2")
    assert me.status_code == 200
    assert me.json()["profile"]["email"] == "verify@example.com"


def test_register_verify_code_then_password_login_works(temp_db, monkeypatch):
    monkeypatch.setattr(main, "EMAIL_PROVIDER", "smtp")
    monkeypatch.setattr(main, "EMAIL_OTP_DEBUG_RETURN_CODE", True)
    with TestClient(main.app) as c:
        register(c, "verified-login@example.com")
        challenge = request_code(c, "verified-login@example.com")
        verify_code(c, challenge.json()["challenge_id"], challenge.json()["debug_code"])
    with TestClient(main.app) as c2:
        logged_in = login(c2, "verified-login@example.com")
        me = c2.get("/api/me-v2")
    assert logged_in.status_code == 200
    assert "onenode_session=" in set_cookies(logged_in)
    assert me.status_code == 200


def test_password_login_existing_verified_user_works_with_provider(temp_db, monkeypatch):
    with TestClient(main.app) as c:
        r = register(c, "old-verified@example.com")
    iuid = r.json()["internal_user_id"]
    with main.db() as conn:
        conn.execute("UPDATE users SET email_verified_at='2026-01-01T00:00:00+00:00' WHERE internal_user_id=?", (iuid,))
    monkeypatch.setattr(main, "EMAIL_PROVIDER", "smtp")
    with TestClient(main.app) as c2:
        logged_in = login(c2, "old-verified@example.com")
    assert logged_in.status_code == 200
    assert "onenode_session=" in set_cookies(logged_in)


def test_no_provider_dev_password_register_login_still_works(temp_db):
    with TestClient(main.app) as c:
        r = register(c, "dev-no-provider@example.com")
        me_after_register = c.get("/api/me-v2")
    assert r.status_code == 200
    assert r.json()["requires_email_verification"] is False
    assert me_after_register.status_code == 200
    with TestClient(main.app) as c2:
        logged_in = login(c2, "dev-no-provider@example.com")
    assert logged_in.status_code == 200


def test_production_without_email_provider_password_register_creates_session(temp_db, monkeypatch):
    monkeypatch.setattr(main, "APP_ENV", "production")
    monkeypatch.setattr(main, "EMAIL_PROVIDER", "")
    monkeypatch.setattr(main, "EMAIL_OTP_DEBUG_RETURN_CODE", False)
    monkeypatch.setattr(main, "bot_login_available", lambda provider: provider in {"telegram", "max"})
    c = TestClient(main.app)
    r = register(c, "prod-no-provider@example.com")
    me = c.get("/api/me-v2")
    assert r.status_code == 200
    assert r.json()["requires_email_verification"] is False
    assert r.json()["social_verification_pending"] is True
    assert r.json()["social_verification_blocks_generation"] is True
    assert "onenode_session=" in set_cookies(r)
    assert me.status_code == 200


def test_capabilities_keep_password_registration_available_without_email_provider(temp_db, monkeypatch):
    monkeypatch.setattr(main, "APP_ENV", "production")
    monkeypatch.setattr(main, "EMAIL_PROVIDER", "")
    monkeypatch.setattr(main, "EMAIL_OTP_DEBUG_RETURN_CODE", False)
    c = TestClient(main.app)
    r = c.get("/api/auth/capabilities-v2")
    assert r.status_code == 200
    assert r.json()["password_register_available"] is True
    assert r.json()["email_otp_available"] is False


def test_change_password_keeps_current_session_and_revokes_other_sessions(temp_db):
    new_password = "N3w-Secure-Password!"
    with TestClient(main.app) as current_client:
        registered = register(current_client, "change-password@example.com")
        assert registered.status_code == 200

        # A plain secondary client keeps a second cookie jar without starting a
        # nested application lifespan (the feed worker is process-global).
        other_client = TestClient(main.app)
        second_login = login(other_client, "change-password@example.com")
        assert second_login.status_code == 200

        changed = change_password(current_client, new_password=new_password)
        assert changed.status_code == 200
        assert changed.json() == {"ok": True, "revoked_sessions": 1}

        assert current_client.get("/api/me-v2").status_code == 200
        assert other_client.get("/api/me-v2").status_code == 401

    with TestClient(main.app) as old_password_client:
        assert login(old_password_client, "change-password@example.com").status_code == 401
    with TestClient(main.app) as new_password_client:
        assert login(new_password_client, "change-password@example.com", password=new_password).status_code == 200


def test_change_password_rejects_wrong_current_and_reused_password(temp_db):
    with TestClient(main.app) as client:
        assert register(client, "password-validation@example.com").status_code == 200

        wrong = change_password(client, current_password="incorrect-password")
        assert wrong.status_code == 400
        assert wrong.json()["detail"] == "Текущий пароль указан неверно."

        reused = change_password(client, new_password=PW)
        assert reused.status_code == 400
        assert reused.json()["detail"] == "Новый пароль должен отличаться от текущего."


def test_me_v2_reports_password_and_registration_metadata(temp_db):
    with TestClient(main.app) as client:
        registered = register(client, "profile-metadata@example.com")
        assert registered.status_code == 200
        me = client.get("/api/me-v2")

    assert me.status_code == 200
    payload = me.json()
    assert payload["account"]["password_configured"] is True
    assert payload["created_at"]
