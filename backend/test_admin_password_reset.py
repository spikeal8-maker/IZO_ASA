"""Admin password reset tests (Phase 16.3).

require_trusted_admin gated endpoint. Temporary SQLite DB.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main


def count(table, where="", params=()):
    with main.db() as conn:
        return conn.execute(f"SELECT COUNT(*) AS c FROM {table} {where}", params).fetchone()["c"]


PW = "Old-Password1!"
NEW_PW = "New-Password2!"


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "pwreset_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    main.init_db()
    now = "2026-01-01T00:00:00+00:00"
    with main.db() as conn:
        conn.execute("INSERT INTO users (id, internal_user_id, language, role, created_at, last_login_at) VALUES (?, ?, 'ru', 'admin', ?, ?)", ("web_admin", "iuid-admin", now, now))
        conn.execute("INSERT INTO auth_identities (id, internal_user_id, legacy_user_id, provider, provider_user_id, linked_at) VALUES (?, ?, ?, 'web_email', 'admin@test.local', ?)", ("id-admin", "iuid-admin", "web_admin", now))
    return db_file


def make_admin_session():
    return main.create_auth_session("iuid-admin", "web_admin", provider="web_email")


def make_user(temp_db):
    """Create a regular user with active password."""
    now = "2026-01-01T00:00:00+00:00"
    iuid = "iuid-testuser"
    legacy = "web_testuser"
    with main.db() as conn:
        conn.execute("INSERT INTO users (id, internal_user_id, language, role, token_balance, created_at, last_login_at) VALUES (?, ?, 'ru', 'user', 100, ?, ?)", (legacy, iuid, now, now))
        conn.execute("INSERT INTO auth_identities (id, internal_user_id, legacy_user_id, provider, provider_user_id, linked_at) VALUES (?, ?, ?, 'web_email', 'user@test.local', ?)", ("id-user", iuid, legacy, now))
        conn.execute("INSERT INTO auth_passwords (id, internal_user_id, password_hash, algorithm, created_at, updated_at, password_updated_at) VALUES (?, ?, ?, 'argon2id', ?, ?, ?)", ("pw-old", iuid, main.hash_password_argon2(PW), now, now, now))
    # Create a session for the user
    main.create_auth_session(iuid, legacy)
    return iuid, legacy


# 1. No session → 401
def test_no_session_401(temp_db):
    iuid, _ = make_user(temp_db)
    with TestClient(main.app) as c:
        r = c.post(f"/api/admin/users/{iuid}/password-reset-v2", json={"new_password": NEW_PW, "reason": "test"})
    assert r.status_code == 401


# 2. Non-admin → 403
def test_non_admin_403(temp_db):
    iuid, legacy = make_user(temp_db)
    user_sess = main.create_auth_session(iuid, legacy, provider="web_email")
    with TestClient(main.app) as c:
        r = c.post(f"/api/admin/users/{iuid}/password-reset-v2", json={"new_password": NEW_PW, "reason": "test"}, cookies={"onenode_session": user_sess["session_token"]})
    assert r.status_code == 403


# 3. Admin can reset password
def test_admin_reset_ok(temp_db):
    iuid, _ = make_user(temp_db)
    admin_sess = make_admin_session()
    assert count("auth_passwords", "WHERE internal_user_id=? AND disabled_at IS NULL", (iuid,)) == 1
    with TestClient(main.app) as c:
        r = c.post(f"/api/admin/users/{iuid}/password-reset-v2", json={"new_password": NEW_PW, "reason": "user forgot password"}, cookies={"onenode_session": admin_sess["session_token"]})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["sessions_revoked"] >= 1


# 4. Old password no longer works
def test_old_password_fails_after_reset(temp_db):
    iuid, legacy = make_user(temp_db)
    admin_sess = make_admin_session()
    with TestClient(main.app) as c:
        c.post(f"/api/admin/users/{iuid}/password-reset-v2", json={"new_password": NEW_PW, "reason": "test"}, cookies={"onenode_session": admin_sess["session_token"]})
    # Try login with old password
    main.create_auth_session(  # need identity for the user
        iuid, legacy, provider="web_email"
    )
    with TestClient(main.app) as c2:
        r = c2.post("/api/auth/password/login-v2", json={"email": "user@test.local", "password": PW})
    assert r.status_code == 401


# 5. New password works
def test_new_password_works_after_reset(temp_db):
    iuid, _ = make_user(temp_db)
    admin_sess = make_admin_session()
    with TestClient(main.app) as c:
        c.post(f"/api/admin/users/{iuid}/password-reset-v2", json={"new_password": NEW_PW, "reason": "test"}, cookies={"onenode_session": admin_sess["session_token"]})
    with TestClient(main.app) as c2:
        r = c2.post("/api/auth/password/login-v2", json={"email": "user@test.local", "password": NEW_PW})
    assert r.status_code == 200 and r.json()["ok"] is True


# 6. Reset revokes existing sessions
def test_reset_revokes_sessions(temp_db):
    iuid, _ = make_user(temp_db)
    assert count("auth_sessions", "WHERE internal_user_id=? AND revoked_at IS NULL", (iuid,)) >= 1
    admin_sess = make_admin_session()
    with TestClient(main.app) as c:
        r = c.post(f"/api/admin/users/{iuid}/password-reset-v2", json={"new_password": NEW_PW, "reason": "test"}, cookies={"onenode_session": admin_sess["session_token"]})
    assert r.json()["sessions_revoked"] >= 1
    assert count("auth_sessions", "WHERE internal_user_id=? AND revoked_at IS NULL", (iuid,)) == 0


# 7. Disabled user remains disabled after reset
def test_disabled_user_stays_disabled(temp_db):
    iuid, legacy = make_user(temp_db)
    with main.db() as conn:
        conn.execute("UPDATE users SET banned=1 WHERE internal_user_id=?", (iuid,))
    admin_sess = make_admin_session()
    with TestClient(main.app) as c:
        r = c.post(f"/api/admin/users/{iuid}/password-reset-v2", json={"new_password": NEW_PW, "reason": "test"}, cookies={"onenode_session": admin_sess["session_token"]})
    assert r.status_code == 200
    with main.db() as conn:
        banned = conn.execute("SELECT banned FROM users WHERE internal_user_id=?", (iuid,)).fetchone()["banned"]
    assert banned == 1  # still banned


# 8. Password policy enforced
def test_password_policy_enforced(temp_db):
    iuid, _ = make_user(temp_db)
    admin_sess = make_admin_session()
    with TestClient(main.app) as c:
        r = c.post(f"/api/admin/users/{iuid}/password-reset-v2", json={"new_password": "short", "reason": "test"}, cookies={"onenode_session": admin_sess["session_token"]})
    assert r.status_code == 400


# 9. Reason required
def test_reason_required(temp_db):
    iuid, _ = make_user(temp_db)
    admin_sess = make_admin_session()
    with TestClient(main.app) as c:
        r = c.post(f"/api/admin/users/{iuid}/password-reset-v2", json={"new_password": NEW_PW, "reason": ""}, cookies={"onenode_session": admin_sess["session_token"]})
    assert r.status_code == 400


# 10. Audit logs written
def test_audit_logs_written(temp_db):
    iuid, _ = make_user(temp_db)
    admin_sess = make_admin_session()
    with TestClient(main.app) as c:
        c.post(f"/api/admin/users/{iuid}/password-reset-v2", json={"new_password": NEW_PW, "reason": "test"}, cookies={"onenode_session": admin_sess["session_token"]})
    assert count("audit_logs", "WHERE action='admin_password_reset'") == 1


# 11. Security events written
def test_security_events_written(temp_db):
    iuid, _ = make_user(temp_db)
    admin_sess = make_admin_session()
    with TestClient(main.app) as c:
        c.post(f"/api/admin/users/{iuid}/password-reset-v2", json={"new_password": NEW_PW, "reason": "test"}, cookies={"onenode_session": admin_sess["session_token"]})
    assert count("security_events", "WHERE event_type='admin_password_reset'") == 1


# 12. Event logs written
def test_event_logs_written(temp_db):
    iuid, _ = make_user(temp_db)
    admin_sess = make_admin_session()
    with TestClient(main.app) as c:
        c.post(f"/api/admin/users/{iuid}/password-reset-v2", json={"new_password": NEW_PW, "reason": "test"}, cookies={"onenode_session": admin_sess["session_token"]})
    assert count("event_logs", "WHERE event_name='admin_password_reset_succeeded'") == 1


# 13. No raw password in logs
def test_no_raw_password_in_logs(temp_db):
    iuid, _ = make_user(temp_db)
    admin_sess = make_admin_session()
    with TestClient(main.app) as c:
        c.post(f"/api/admin/users/{iuid}/password-reset-v2", json={"new_password": NEW_PW, "reason": "test"}, cookies={"onenode_session": admin_sess["session_token"]})
    with main.db() as conn:
        for table in ("audit_logs", "security_events", "event_logs"):
            for row in conn.execute(f"SELECT * FROM {table}").fetchall():
                blob = " ".join(str(v) for v in tuple(row))
                assert NEW_PW not in blob, f"raw password leaked into {table}"


# 14. No password_hash in logs
def test_no_password_hash_in_logs(temp_db):
    iuid, _ = make_user(temp_db)
    admin_sess = make_admin_session()
    with TestClient(main.app) as c:
        c.post(f"/api/admin/users/{iuid}/password-reset-v2", json={"new_password": NEW_PW, "reason": "test"}, cookies={"onenode_session": admin_sess["session_token"]})
    with main.db() as conn:
        pwhash = conn.execute("SELECT password_hash FROM auth_passwords WHERE internal_user_id=? AND disabled_at IS NULL", (iuid,)).fetchone()["password_hash"]
        for table in ("audit_logs", "security_events", "event_logs"):
            for row in conn.execute(f"SELECT * FROM {table}").fetchall():
                blob = " ".join(str(v) for v in tuple(row))
                assert pwhash not in blob, f"password_hash leaked into {table}"


# 15. users.id unchanged
def test_users_id_unchanged(temp_db):
    with main.db() as conn:
        conn.execute("INSERT INTO users (id, internal_user_id, language, role, created_at, last_login_at) VALUES ('telegram_legacy3','iuid-legacy3','ru','user','2026-01-01','2026-01-01')")
        before = sorted(r["id"] for r in conn.execute("SELECT id FROM users"))
    iuid, _ = make_user(temp_db)
    admin_sess = make_admin_session()
    with TestClient(main.app) as c:
        c.post(f"/api/admin/users/{iuid}/password-reset-v2", json={"new_password": NEW_PW, "reason": "test"}, cookies={"onenode_session": admin_sess["session_token"]})
    with main.db() as conn:
        after = sorted(r["id"] for r in conn.execute("SELECT id FROM users"))
    assert "telegram_legacy3" in after
    assert all(i in after for i in before)


# 16. User not found → 404
def test_user_not_found_404(temp_db):
    admin_sess = make_admin_session()
    with TestClient(main.app) as c:
        r = c.post("/api/admin/users/nonexistent-iuid/password-reset-v2", json={"new_password": NEW_PW, "reason": "test"}, cookies={"onenode_session": admin_sess["session_token"]})
    assert r.status_code == 404
