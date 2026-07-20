"""Account lifecycle consistency tests (Phase 16.2).

Tests admin safe-disable, password register/login orphan handling,
banned user handling.
Temporary SQLite DB via monkeypatching main.DB_PATH; working DB never touched.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from test_support.browser_origin import BROWSER_ORIGIN


def count(table, where="", params=()):
    with main.db() as conn:
        return conn.execute(f"SELECT COUNT(*) AS c FROM {table} {where}", params).fetchone()["c"]


PW = "S3cret-Password!"
_ADMIN_SESSION: dict[str, str] = {}


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "lifecycle_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    main.init_db()
    # Create a real trusted admin session. Legacy identity headers must never
    # authorize protected lifecycle operations.
    now = "2026-01-01T00:00:00+00:00"
    with main.db() as conn:
        conn.execute("INSERT INTO users (id, internal_user_id, language, role, created_at, last_login_at) VALUES (?, ?, 'ru', 'admin', ?, ?)",
                     ("web_admin", "iuid-admin", now, now))
    session = main.create_auth_session("iuid-admin", "web_admin", provider="web_email", platform="web_desktop")
    _ADMIN_SESSION["token"] = session["session_token"]
    yield db_file
    _ADMIN_SESSION.clear()


def admin_client() -> TestClient:
    client = TestClient(main.app)
    client.cookies.set(main.TRUSTED_SESSION_COOKIE_NAME, _ADMIN_SESSION["token"])
    # Browser-faithful: cookie-auth unsafe methods carry an allowlisted Origin
    # to pass the CSRF boundary (AUTH-LEGACY-001B).
    client.headers.update(BROWSER_ORIGIN)
    return client


def register(client, email, password=PW, repeat=None):
    return client.post("/api/auth/password/register-v2", json={
        "email": email, "password": password, "password_repeat": repeat if repeat is not None else password,
        "accepted_terms": True, "accepted_privacy": True, "accepted_personal_data": True,
    })


def login(client, email, password=PW):
    return client.post("/api/auth/password/login-v2", json={"email": email, "password": password})


# --- 1. Active user can register and login ---
def test_active_user_register_and_login(temp_db):
    with TestClient(main.app) as c:
        r = register(c, "lifecycle@test.local")
    assert r.status_code == 200 and r.json()["ok"] is True
    with TestClient(main.app) as c2:
        r = login(c2, "lifecycle@test.local")
    assert r.status_code == 200 and r.json()["ok"] is True


# --- 2. Wrong password returns 401 generic ---
def test_wrong_password_401(temp_db):
    with TestClient(main.app) as c:
        register(c, "wp@test.local")
    with TestClient(main.app) as c2:
        r = login(c2, "wp@test.local", password="totally-wrong")
    assert r.status_code == 401
    assert r.json()["detail"] == "Неверная почта или пароль."


# --- 3. Unknown email returns same 401 generic ---
def test_unknown_email_401(temp_db):
    with TestClient(main.app) as c:
        r = login(c, "unknown@test.local")
    assert r.status_code == 401
    assert r.json()["detail"] == "Неверная почта или пароль."


# --- 4. Banned user cannot login (403) ---
def test_banned_user_login_403(temp_db):
    with TestClient(main.app) as c:
        r = register(c, "ban@test.local")
        iuid = r.json()["internal_user_id"]
    with main.db() as conn:
        conn.execute("UPDATE users SET banned=1 WHERE internal_user_id=?", (iuid,))
    with TestClient(main.app) as c2:
        r = login(c2, "ban@test.local")
    assert r.status_code == 403


# --- 5. Admin disable revokes sessions ---
def test_admin_disable_revokes_sessions(temp_db):
    with TestClient(main.app) as c:
        r = register(c, "revoke@test.local")
        legacy = r.json()["legacy_user_id"]
        iuid = r.json()["internal_user_id"]
    # Verify session is active
    assert count("auth_sessions", "WHERE internal_user_id=? AND revoked_at IS NULL", (iuid,)) >= 1
    # Admin disable
    with admin_client() as c2:
        r = c2.delete(f"/api/admin/users/{legacy}")
    assert r.status_code == 200
    # Sessions revoked
    assert count("auth_sessions", "WHERE internal_user_id=? AND revoked_at IS NULL", (iuid,)) == 0


# --- 6. Admin disable disables active password ---
def test_admin_disable_disables_password(temp_db):
    with TestClient(main.app) as c:
        r = register(c, "pwdisable@test.local")
        legacy = r.json()["legacy_user_id"]
        iuid = r.json()["internal_user_id"]
    assert count("auth_passwords", "WHERE internal_user_id=? AND disabled_at IS NULL", (iuid,)) == 1
    with admin_client() as c2:
        response = c2.delete(f"/api/admin/users/{legacy}")
    assert response.status_code == 200
    assert count("auth_passwords", "WHERE internal_user_id=? AND disabled_at IS NULL", (iuid,)) == 0


# --- 7. Registering same disabled email returns 409 ---
def test_register_disabled_email_409(temp_db):
    with TestClient(main.app) as c:
        r = register(c, "disabled@test.local")
        legacy = r.json()["legacy_user_id"]
    # Admin disable
    with admin_client() as c2:
        response = c2.delete(f"/api/admin/users/{legacy}")
    assert response.status_code == 200
    # Try re-register
    with TestClient(main.app) as c3:
        r = register(c3, "disabled@test.local")
    assert r.status_code == 409


# --- 8. Orphan auth_identity with missing user cannot login ---
def test_orphan_identity_cannot_login(temp_db):
    now = "2026-01-01T00:00:00+00:00"
    with main.db() as conn:
        conn.execute("INSERT INTO auth_identities (id, internal_user_id, provider, provider_user_id, linked_at) VALUES (?, ?, 'web_email', ?, ?)",
                     ("oid-orphan", "iuid-orphan", "orphan@test.local", now))
    with TestClient(main.app) as c:
        r = login(c, "orphan@test.local")
    assert r.status_code == 401
    assert r.json()["detail"] == "Неверная почта или пароль."
    assert count("security_events", "WHERE event_type='password_login_orphan_identity'") == 1


# --- 9. Orphan auth_password with missing user cannot login ---
def test_orphan_password_cannot_login(temp_db):
    now = "2026-01-01T00:00:00+00:00"
    # Create identity without user
    with main.db() as conn:
        conn.execute("INSERT INTO auth_identities (id, internal_user_id, provider, provider_user_id, linked_at) VALUES (?, ?, 'web_email', ?, ?)",
                     ("oid-pw", "iuid-pw-orphan", "pworphan@test.local", now))
        conn.execute("INSERT INTO auth_passwords (id, internal_user_id, password_hash, algorithm, created_at, updated_at) VALUES (?, ?, ?, 'argon2id', ?, ?)",
                     ("pw-orphan", "iuid-pw-orphan", main._DUMMY_PASSWORD_HASH, now, now))
    with TestClient(main.app) as c:
        r = login(c, "pworphan@test.local")
    assert r.status_code == 401


# --- 10. Orphan identity does not create duplicate user silently ---
def test_orphan_register_no_duplicate(temp_db):
    now = "2026-01-01T00:00:00+00:00"
    with main.db() as conn:
        conn.execute("INSERT INTO auth_identities (id, internal_user_id, provider, provider_user_id, linked_at) VALUES (?, ?, 'web_email', ?, ?)",
                     ("oid-dup", "iuid-dup", "nouser@test.local", now))
    before = count("users")
    with TestClient(main.app) as c:
        r = register(c, "nouser@test.local")
    assert r.status_code == 409
    assert count("users") == before
    assert count("security_events", "WHERE event_type='password_register_orphan_identity'") == 1


# --- 11. No raw password logged ---
def test_no_raw_password_logged(temp_db):
    with TestClient(main.app) as c:
        register(c, "nolog@test.local")
    with main.db() as conn:
        for table in ("security_events", "event_logs"):
            for row in conn.execute(f"SELECT * FROM {table}").fetchall():
                blob = " ".join(str(v) for v in tuple(row))
                assert PW not in blob, f"raw password leaked into {table}"


# --- 12. No password_hash logged ---
def test_no_password_hash_logged(temp_db):
    with TestClient(main.app) as c:
        r = register(c, "nohash@test.local")
        iuid = r.json()["internal_user_id"]
    with main.db() as conn:
        pw = conn.execute("SELECT password_hash FROM auth_passwords WHERE internal_user_id=?", (iuid,)).fetchone()
    assert pw is not None
    pwhash = pw["password_hash"]
    with main.db() as conn:
        for table in ("security_events", "event_logs"):
            for row in conn.execute(f"SELECT * FROM {table}").fetchall():
                blob = " ".join(str(v) for v in tuple(row))
                assert pwhash not in blob, f"password_hash leaked into {table}"


# --- 13. users.id unchanged ---
def test_users_id_unchanged(temp_db):
    with main.db() as conn:
        conn.execute("INSERT INTO users (id, internal_user_id, language, role, created_at, last_login_at) VALUES ('telegram_legacy2','iuid-leg2','ru','user','2026-01-01','2026-01-01')")
        before = sorted(r["id"] for r in conn.execute("SELECT id FROM users"))
    with TestClient(main.app) as c:
        register(c, "idtest@test.local")
    with main.db() as conn:
        after = sorted(r["id"] for r in conn.execute("SELECT id FROM users"))
    assert "telegram_legacy2" in after
    assert all(i in after for i in before)


# --- 14. Admin disable: protected users cannot be disabled ---
def test_admin_delete_protected_users_400(temp_db):
    with admin_client() as c:
        r = c.delete("/api/admin/users/web_admin")
    assert r.status_code == 400
    with admin_client() as c2:
        r = c2.delete("/api/admin/users/demo_user")
    assert r.status_code == 400
