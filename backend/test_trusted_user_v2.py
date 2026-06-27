"""Trusted user v2 + /api/me-v2 tests (Phase 9).

All tests use a TEMPORARY SQLite DB via monkeypatching main.DB_PATH;
backend/onenode.sqlite3 is never touched.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "trusted_user_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    main.init_db()
    return db_file


NOW = "2026-06-25T00:00:00+00:00"


def make_user(internal_user_id, legacy_user_id, *, role="user", banned=0, username=None, first_name="Ann"):
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, internal_user_id, username, first_name, language, role, created_at, last_login_at, banned, last_seen_at) "
            "VALUES (?, ?, ?, ?, 'ru', ?, ?, ?, ?, ?)",
            (legacy_user_id, internal_user_id, username, first_name, role, NOW, NOW, banned, NOW),
        )


def make_identity(internal_user_id, legacy_user_id, provider="telegram", pid="1", email=None, username=None):
    with main.db() as conn:
        conn.execute(
            "INSERT INTO auth_identities (id, internal_user_id, legacy_user_id, provider, provider_user_id, provider_username, provider_email, linked_at, last_login_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (main.uuid.uuid4().hex, internal_user_id, legacy_user_id, provider, pid, username, email, NOW, NOW),
        )


def session_for(internal_user_id, legacy_user_id, provider="telegram", platform="telegram_mini_app"):
    return main.create_auth_session(internal_user_id, legacy_user_id, provider=provider, platform=platform)


def count(table, where="", params=()):
    with main.db() as conn:
        return conn.execute(f"SELECT COUNT(*) AS c FROM {table} {where}", params).fetchone()["c"]


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


# 1
def test_me_v2_without_session_401(temp_db):
    with TestClient(main.app) as client:
        r = client.get("/api/me-v2")
    assert r.status_code == 401


# 2
def test_me_v2_with_valid_session(temp_db):
    make_user("iuid-1", "telegram_1", username="ann")
    make_identity("iuid-1", "telegram_1", provider="telegram", pid="1", username="ann")
    s = session_for("iuid-1", "telegram_1")
    with TestClient(main.app) as client:
        r = client.get("/api/me-v2", headers=bearer(s["session_token"]))
    assert r.status_code == 200
    b = r.json()
    assert b["internal_user_id"] == "iuid-1"
    assert b["legacy_user_id"] == "telegram_1"
    assert b["status"] == "active"
    assert b["session"]["session_id"] == s["session_id"]
    # Phase 18: display_name priority is first+last name before username.
    assert b["profile"]["display_name"] == "Ann"


# 3
def test_me_v2_does_not_use_header_without_session(temp_db):
    make_user("iuid-admin", "admin", role="admin")
    with TestClient(main.app) as client:
        r = client.get("/api/me-v2", headers={"X-OneNode-User": "admin"})
    assert r.status_code == 401


# 4 & 5
def test_me_v2_ignores_header_spoof_and_logs(temp_db):
    make_user("iuid-1", "telegram_1")
    make_user("iuid-admin", "admin", role="admin")
    s = session_for("iuid-1", "telegram_1")
    with TestClient(main.app) as client:
        r = client.get("/api/me-v2", headers={**bearer(s["session_token"]), "X-OneNode-User": "admin"})
    assert r.status_code == 200
    assert r.json()["legacy_user_id"] == "telegram_1"  # not 'admin'
    assert count("security_events", "WHERE event_type='legacy_identity_spoof_attempt'") == 1


# 6
def test_me_v2_ignores_cookie_spoof(temp_db):
    make_user("iuid-1", "telegram_1")
    make_user("iuid-admin", "admin", role="admin")
    s = session_for("iuid-1", "telegram_1")
    with TestClient(main.app) as client:
        client.cookies.set("onenode_user", "admin")
        r = client.get("/api/me-v2", headers=bearer(s["session_token"]))
    assert r.status_code == 200
    assert r.json()["legacy_user_id"] == "telegram_1"


# 7
def test_me_v2_ignores_query_user_id(temp_db):
    make_user("iuid-1", "telegram_1")
    s = session_for("iuid-1", "telegram_1")
    with TestClient(main.app) as client:
        r = client.get("/api/me-v2?user_id=admin&internal_user_id=iuid-admin", headers=bearer(s["session_token"]))
    assert r.status_code == 200
    assert r.json()["internal_user_id"] == "iuid-1"


# 8
def test_revoked_session_401(temp_db):
    make_user("iuid-1", "telegram_1")
    s = session_for("iuid-1", "telegram_1")
    main.revoke_auth_session(s["session_id"], reason="manual")
    with TestClient(main.app) as client:
        r = client.get("/api/me-v2", headers=bearer(s["session_token"]))
    assert r.status_code == 401


# 9
def test_expired_session_401(temp_db):
    make_user("iuid-1", "telegram_1")
    s = session_for("iuid-1", "telegram_1")
    with main.db() as conn:
        conn.execute("UPDATE auth_sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (s["session_id"],))
    with TestClient(main.app) as client:
        r = client.get("/api/me-v2", headers=bearer(s["session_token"]))
    assert r.status_code == 401


# 10
def test_banned_user_403(temp_db):
    make_user("iuid-ban", "telegram_ban", banned=1)
    s = session_for("iuid-ban", "telegram_ban")
    with TestClient(main.app) as client:
        r = client.get("/api/me-v2", headers=bearer(s["session_token"]))
    assert r.status_code == 403


def test_deleted_user_403(temp_db):
    make_user("iuid-del", "telegram_del")
    s = session_for("iuid-del", "telegram_del")
    with main.db() as conn:
        conn.execute("DELETE FROM users WHERE id='telegram_del'")
    with TestClient(main.app) as client:
        r = client.get("/api/me-v2", headers=bearer(s["session_token"]))
    assert r.status_code == 403


# 11, 12, 13, 14
def test_response_does_not_expose_secrets(temp_db):
    make_user("iuid-1", "telegram_1")
    make_identity("iuid-1", "telegram_1")
    s = session_for("iuid-1", "telegram_1")
    with TestClient(main.app) as client:
        r = client.get("/api/me-v2", headers=bearer(s["session_token"]))
    text = r.text
    assert "session_token_hash" not in text
    assert "refresh_token_hash" not in text
    assert "code_hash" not in text
    assert s["session_token"] not in text
    assert s["refresh_token"] not in text
    # the actual stored hash value must not leak either
    with main.db() as conn:
        h = conn.execute("SELECT session_token_hash, refresh_token_hash FROM auth_sessions WHERE id=?", (s["session_id"],)).fetchone()
    assert h["session_token_hash"] not in text
    assert h["refresh_token_hash"] not in text


# 15
def test_identities_for_trusted_user_only(temp_db):
    make_user("iuid-1", "telegram_1")
    make_user("iuid-2", "telegram_2")
    make_identity("iuid-1", "telegram_1", provider="telegram", pid="1", email=None, username="me")
    make_identity("iuid-2", "telegram_2", provider="telegram", pid="2", email="other@x.com", username="other")
    s = session_for("iuid-1", "telegram_1")
    with TestClient(main.app) as client:
        r = client.get("/api/me-v2", headers=bearer(s["session_token"]))
    idents = r.json()["identities"]
    assert len(idents) == 1
    assert idents[0]["provider_username"] == "me"
    assert "other@x.com" not in r.text


# 16
def test_user_a_cannot_get_user_b(temp_db):
    make_user("iuid-a", "telegram_a", username="aaa")
    make_user("iuid-b", "telegram_b", username="bbb")
    sa = session_for("iuid-a", "telegram_a")
    with TestClient(main.app) as client:
        # A authenticates but tries to impersonate B via headers/cookies/query
        client.cookies.set("onenode_user", "telegram_b")
        r = client.get("/api/me-v2?user_id=telegram_b&internal_user_id=iuid-b",
                       headers={**bearer(sa["session_token"]), "X-OneNode-User": "telegram_b"})
    assert r.json()["internal_user_id"] == "iuid-a"


# 17
def test_require_trusted_admin_ignores_header(temp_db):
    # non-admin user with a valid session, plus an admin in the DB
    make_user("iuid-user", "telegram_user", role="user")
    make_user("iuid-admin", "admin", role="admin")
    s = session_for("iuid-user", "telegram_user")

    class FakeReq:
        headers = {"authorization": f"Bearer {s['session_token']}", "x-onenode-user": "admin"}
        cookies = {}
        client = None

    with pytest.raises(main.HTTPException) as exc:
        main.require_trusted_admin(FakeReq())
    assert exc.value.status_code == 403


# 18
def test_trusted_admin_passes_for_admin_role(temp_db):
    make_user("iuid-admin", "telegram_admin", role="admin")
    s = session_for("iuid-admin", "telegram_admin")

    class FakeReq:
        headers = {"authorization": f"Bearer {s['session_token']}"}
        cookies = {}
        client = None

    user = main.require_trusted_admin(FakeReq())
    assert user["internal_user_id"] == "iuid-admin"

    # a non-admin is rejected
    make_user("iuid-u", "telegram_u", role="user")
    s2 = session_for("iuid-u", "telegram_u")

    class FakeReq2:
        headers = {"authorization": f"Bearer {s2['session_token']}"}
        cookies = {}
        client = None

    with pytest.raises(main.HTTPException) as exc:
        main.require_trusted_admin(FakeReq2())
    assert exc.value.status_code == 403


# 19 — admin role IS safely determinable (users.role exists); admin-v2 endpoints
# are still NOT implemented in this phase, only the helper.
def test_admin_v2_endpoints_not_added(temp_db):
    routes = {r.path for r in main.app.routes}
    assert "/api/me-v2" in routes
    assert not any(p.startswith("/api/admin-v2") or p.endswith("/admin-v2") for p in routes)


# 21
def test_legacy_auth_functions_unchanged():
    import inspect
    ru = inspect.getsource(main.request_user_id)
    ra = inspect.getsource(main.require_admin)
    assert "X-OneNode-User" in ru  # still the legacy header-trusting impl
    assert "auth_sessions" not in ru
    assert "auth_sessions" not in ra


# 22
def test_v2_login_endpoints_present():
    routes = {r.path for r in main.app.routes}
    for p in ("/api/auth/telegram-v2", "/api/auth/max-v2",
              "/api/auth/email/request-code-v2", "/api/auth/email/verify-code-v2"):
        assert p in routes
