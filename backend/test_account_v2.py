"""Profile / Devices / Consents v2 tests (Phase 11).

All tests use a TEMPORARY SQLite DB via monkeypatching main.DB_PATH;
backend/onenode.sqlite3 is never touched.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main


NOW = "2026-06-25T00:00:00+00:00"


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "account_v2_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    main.init_db()
    return db_file


def make_user(iuid, legacy, *, role="user", banned=0, username=None, first_name="Ann"):
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, internal_user_id, username, first_name, language, role, created_at, last_login_at, banned, last_seen_at) "
            "VALUES (?, ?, ?, ?, 'ru', ?, ?, ?, ?, ?)",
            (legacy, iuid, username, first_name, role, NOW, NOW, banned, NOW),
        )


def make_identity(iuid, legacy, provider="telegram", pid="1", email=None, username=None):
    with main.db() as conn:
        conn.execute(
            "INSERT INTO auth_identities (id, internal_user_id, legacy_user_id, provider, provider_user_id, provider_username, provider_email, linked_at, last_login_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (main.uuid.uuid4().hex, iuid, legacy, provider, pid, username, email, NOW, NOW),
        )


def make_device(iuid, legacy, installation_id, platform="web_desktop", metadata=None):
    import json
    with main.db() as conn:
        conn.execute(
            "INSERT INTO device_installations (id, internal_user_id, legacy_user_id, installation_id, anonymous_id, platform, storage_type, first_seen_at, last_seen_at, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (main.uuid.uuid4().hex, iuid, legacy, installation_id, "anon", platform, "local_storage", NOW, NOW, json.dumps(metadata or {})),
        )


def session_for(iuid, legacy, provider="telegram", platform="telegram_mini_app"):
    return main.create_auth_session(iuid, legacy, provider=provider, platform=platform)


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def count(table, where="", params=()):
    with main.db() as conn:
        return conn.execute(f"SELECT COUNT(*) AS c FROM {table} {where}", params).fetchone()["c"]


# 1
def test_profile_without_session_401(temp_db):
    with TestClient(main.app) as client:
        assert client.get("/api/me/profile-v2").status_code == 401


# 2
def test_profile_valid_session(temp_db):
    make_user("iuid-1", "telegram_1", username="ann")
    make_identity("iuid-1", "telegram_1", username="ann", email="a@x.com")
    s = session_for("iuid-1", "telegram_1")
    with TestClient(main.app) as client:
        r = client.get("/api/me/profile-v2", headers=bearer(s["session_token"]))
    assert r.status_code == 200
    b = r.json()
    assert b["internal_user_id"] == "iuid-1"
    assert b["profile"]["username"] == "ann"
    assert len(b["identities"]) == 1


# 3
def test_x_header_spoof_ignored(temp_db):
    make_user("iuid-1", "telegram_1", username="real")
    make_user("iuid-admin", "admin", role="admin", username="boss")
    s = session_for("iuid-1", "telegram_1")
    with TestClient(main.app) as client:
        r = client.get("/api/me/profile-v2", headers={**bearer(s["session_token"]), "X-OneNode-User": "admin"})
    assert r.json()["internal_user_id"] == "iuid-1"


# 4
def test_cookie_spoof_ignored(temp_db):
    make_user("iuid-1", "telegram_1")
    make_user("iuid-admin", "admin", role="admin")
    s = session_for("iuid-1", "telegram_1")
    with TestClient(main.app) as client:
        client.cookies.set("onenode_user", "admin")
        r = client.get("/api/me/profile-v2", headers=bearer(s["session_token"]))
    assert r.json()["internal_user_id"] == "iuid-1"


# 5
def test_query_body_user_id_ignored(temp_db):
    make_user("iuid-1", "telegram_1")
    make_user("iuid-2", "telegram_2")
    s = session_for("iuid-1", "telegram_1")
    with TestClient(main.app) as client:
        r = client.get("/api/me/profile-v2?user_id=iuid-2&internal_user_id=iuid-2", headers=bearer(s["session_token"]))
    assert r.json()["internal_user_id"] == "iuid-1"


# 6, 7
def test_profile_no_secret_fields(temp_db):
    make_user("iuid-1", "telegram_1")
    make_identity("iuid-1", "telegram_1")
    s = session_for("iuid-1", "telegram_1")
    with TestClient(main.app) as client:
        r = client.get("/api/me/profile-v2", headers=bearer(s["session_token"]))
    text = r.text
    for forbidden in ("session_token_hash", "refresh_token_hash", "raw_profile_json", "code_hash"):
        assert forbidden not in text
    assert s["session_token"] not in text


# 8
def test_patch_updates_allowed_fields(temp_db):
    make_user("iuid-1", "telegram_1", username="old")
    s = session_for("iuid-1", "telegram_1")
    with TestClient(main.app) as client:
        r = client.patch(
            "/api/me/profile-v2",
            json={
                "display_name": " New Name ",
                "city": "Berlin",
                "language_code": "en",
                "public_about": " Создаю визуалы для брендов ",
                "public_website": "example.com/portfolio",
                "public_focus": "бренд-дизайн",
                "public_phone": " +7 900 000-00-00 ",
                "public_links": [
                    {"label": "Telegram", "url": "t.me/brand"},
                    {"label": "Портфолио", "url": "https://portfolio.example"},
                ],
            },
                         headers=bearer(s["session_token"]))
        me = client.get("/api/me-v2", headers=bearer(s["session_token"]))
    assert r.status_code == 200
    p = r.json()["profile"]
    assert p["display_name"] == "New Name"  # trimmed
    assert p["city"] == "Berlin"
    assert p["language_code"] == "en"
    assert p["public_about"] == "Создаю визуалы для брендов"
    assert p["public_website"] == "https://example.com/portfolio"
    assert p["public_focus"] == "бренд-дизайн"
    assert p["public_phone"] == "+7 900 000-00-00"
    assert p["public_links"] == [
        {"label": "Telegram", "url": "https://t.me/brand"},
        {"label": "Портфолио", "url": "https://portfolio.example"},
    ]
    assert me.json()["profile"]["public_website"] == "https://example.com/portfolio"
    assert me.json()["profile"]["public_links"][0]["url"] == "https://t.me/brand"
    with main.db() as conn:
        row = conn.execute("SELECT public_about, public_website, public_focus, public_phone, public_links_json FROM users WHERE internal_user_id='iuid-1'").fetchone()
    assert row["public_about"] == "Создаю визуалы для брендов"
    assert row["public_website"] == "https://example.com/portfolio"
    assert row["public_focus"] == "бренд-дизайн"
    assert row["public_phone"] == "+7 900 000-00-00"
    assert '"https://t.me/brand"' in row["public_links_json"]


# 9, 10, 11, 12
def test_patch_cannot_change_protected_fields(temp_db):
    make_user("iuid-1", "telegram_1", role="user", banned=0)
    s = session_for("iuid-1", "telegram_1")
    with TestClient(main.app) as client:
        r = client.patch("/api/me/profile-v2",
                         json={"role": "admin", "banned": 1, "internal_user_id": "iuid-hacked", "id": "telegram_hacked", "first_name": "Ok"},
                         headers=bearer(s["session_token"]))
    assert r.status_code == 200
    with main.db() as conn:
        row = conn.execute("SELECT id, internal_user_id, role, banned, first_name FROM users WHERE internal_user_id='iuid-1'").fetchone()
    assert row["id"] == "telegram_1"
    assert row["internal_user_id"] == "iuid-1"
    assert row["role"] == "user"
    assert row["banned"] == 0
    assert row["first_name"] == "Ok"  # allowed field did update


# 13
def test_patch_writes_event_log(temp_db):
    make_user("iuid-1", "telegram_1")
    s = session_for("iuid-1", "telegram_1")
    with TestClient(main.app) as client:
        client.patch("/api/me/profile-v2", json={"first_name": "Z"}, headers=bearer(s["session_token"]))
    assert count("event_logs", "WHERE event_name='profile_updated'") == 1


# 14, 15
def test_devices_only_current_user_sanitized(temp_db):
    make_user("iuid-1", "telegram_1")
    make_user("iuid-2", "telegram_2")
    make_device("iuid-1", "telegram_1", "inst-1", metadata={"client": {"language": "ru", "timezone": "UTC", "app_version": "1.2", "screen_width": 1440}, "utm": {"source": "x"}})
    make_device("iuid-2", "telegram_2", "inst-2")
    s = session_for("iuid-1", "telegram_1")
    with TestClient(main.app) as client:
        r = client.get("/api/me/devices-v2", headers=bearer(s["session_token"]))
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["installation_id"] == "inst-1"
    meta = items[0]["metadata"]
    assert set(meta.keys()) == {"language", "timezone", "app_version"}  # screen_width/utm not exposed
    assert meta["language"] == "ru"


# 16, 17
def test_sessions_only_current_user_no_hashes(temp_db):
    make_user("iuid-1", "telegram_1")
    make_user("iuid-2", "telegram_2")
    s1 = session_for("iuid-1", "telegram_1")
    session_for("iuid-1", "telegram_1")  # second session for user 1
    session_for("iuid-2", "telegram_2")  # other user
    with TestClient(main.app) as client:
        r = client.get("/api/me/sessions-v2", headers=bearer(s1["session_token"]))
    items = r.json()["items"]
    assert len(items) == 2  # only user 1's sessions
    assert any(i["is_current"] for i in items)
    text = r.text
    assert "session_token_hash" not in text and "refresh_token_hash" not in text
    assert s1["session_token"] not in text


# 18
def test_consents_initially_empty(temp_db):
    make_user("iuid-1", "telegram_1")
    s = session_for("iuid-1", "telegram_1")
    with TestClient(main.app) as client:
        r = client.get("/api/me/consents-v2", headers=bearer(s["session_token"]))
    assert r.json()["items"] == []


# 19, 20
def test_post_consent_accepted(temp_db):
    make_user("iuid-1", "telegram_1")
    s = session_for("iuid-1", "telegram_1")
    with TestClient(main.app) as client:
        r = client.post("/api/me/consents-v2", json={"consent_type": "terms", "document_version": "v1", "accepted": True},
                        headers=bearer(s["session_token"]))
    assert r.status_code == 200
    assert r.json()["accepted"] is True and r.json()["revoked_at"] is None
    assert count("user_consents", "WHERE internal_user_id='iuid-1' AND consent_type='terms'") == 1
    assert count("event_logs", "WHERE event_name='consent_accepted'") == 1


# 21
def test_post_consent_revoked(temp_db):
    make_user("iuid-1", "telegram_1")
    s = session_for("iuid-1", "telegram_1")
    with TestClient(main.app) as client:
        # accept then revoke -> two historical rows, never overwritten
        client.post("/api/me/consents-v2", json={"consent_type": "marketing", "document_version": "v1", "accepted": True}, headers=bearer(s["session_token"]))
        r = client.post("/api/me/consents-v2", json={"consent_type": "marketing", "document_version": "v1", "accepted": False}, headers=bearer(s["session_token"]))
    assert r.json()["accepted"] is False and r.json()["revoked_at"] is not None
    assert count("user_consents", "WHERE consent_type='marketing'") == 2  # history preserved
    assert count("event_logs", "WHERE event_name='consent_revoked'") == 1


# 22
def test_invalid_consent_type_400(temp_db):
    make_user("iuid-1", "telegram_1")
    s = session_for("iuid-1", "telegram_1")
    with TestClient(main.app) as client:
        r = client.post("/api/me/consents-v2", json={"consent_type": "totally_made_up", "document_version": "v1"}, headers=bearer(s["session_token"]))
    assert r.status_code == 400


# 23
def test_missing_document_version_400(temp_db):
    make_user("iuid-1", "telegram_1")
    s = session_for("iuid-1", "telegram_1")
    with TestClient(main.app) as client:
        r = client.post("/api/me/consents-v2", json={"consent_type": "terms", "document_version": "   "}, headers=bearer(s["session_token"]))
    assert r.status_code == 400


# 24
def test_user_a_cannot_see_user_b_data(temp_db):
    make_user("iuid-a", "telegram_a")
    make_user("iuid-b", "telegram_b")
    make_device("iuid-b", "telegram_b", "inst-b")
    session_for("iuid-b", "telegram_b")
    with main.db() as conn:
        conn.execute("INSERT INTO user_consents (id, internal_user_id, consent_type, document_version, accepted, accepted_at) "
                     "VALUES ('cb','iuid-b','terms','v1',1, ?)", (NOW,))
    sa = session_for("iuid-a", "telegram_a")
    with TestClient(main.app) as client:
        h = {**bearer(sa["session_token"]), "X-OneNode-User": "telegram_b"}
        client.cookies.set("onenode_user", "telegram_b")
        devices = client.get("/api/me/devices-v2?internal_user_id=iuid-b", headers=h).json()["items"]
        sessions = client.get("/api/me/sessions-v2?internal_user_id=iuid-b", headers=h).json()["items"]
        consents = client.get("/api/me/consents-v2?internal_user_id=iuid-b", headers=h).json()["items"]
    assert devices == []           # A has no devices; B's not visible
    assert all(i["id"] != "cb" for i in sessions)
    assert consents == []


# Audit hardening (11.1): cross-user PATCH cannot touch another user.
def test_patch_cannot_affect_other_user(temp_db):
    make_user("iuid-a", "telegram_a", first_name="A-orig")
    make_user("iuid-b", "telegram_b", first_name="B-orig")
    sa = session_for("iuid-a", "telegram_a")
    with TestClient(main.app) as client:
        client.cookies.set("onenode_user", "telegram_b")
        client.patch("/api/me/profile-v2?internal_user_id=iuid-b",
                     json={"first_name": "HACKED", "internal_user_id": "iuid-b"},
                     headers={**bearer(sa["session_token"]), "X-OneNode-User": "telegram_b"})
    with main.db() as conn:
        a = conn.execute("SELECT first_name FROM users WHERE internal_user_id='iuid-a'").fetchone()["first_name"]
        b = conn.execute("SELECT first_name FROM users WHERE internal_user_id='iuid-b'").fetchone()["first_name"]
    assert a == "HACKED"      # only the trusted user A was updated
    assert b == "B-orig"      # B untouched


# Audit hardening: PATCH enforces max length (200 chars).
def test_patch_enforces_max_length(temp_db):
    make_user("iuid-1", "telegram_1")
    s = session_for("iuid-1", "telegram_1")
    long = "x" * 5000
    with TestClient(main.app) as client:
        r = client.patch("/api/me/profile-v2", json={"display_name": long}, headers=bearer(s["session_token"]))
    assert r.status_code == 200
    assert len(r.json()["profile"]["display_name"]) == 200


# Audit hardening: a consent is always attributed to the trusted user, even under spoof.
def test_consent_attributed_to_trusted_user_only(temp_db):
    make_user("iuid-a", "telegram_a")
    make_user("iuid-b", "telegram_b")
    sa = session_for("iuid-a", "telegram_a")
    with TestClient(main.app) as client:
        client.cookies.set("onenode_user", "telegram_b")
        client.post("/api/me/consents-v2?internal_user_id=iuid-b",
                    json={"consent_type": "terms", "document_version": "v1", "accepted": True, "internal_user_id": "iuid-b"},
                    headers={**bearer(sa["session_token"]), "X-OneNode-User": "telegram_b"})
    assert count("user_consents", "WHERE internal_user_id='iuid-a'") == 1
    assert count("user_consents", "WHERE internal_user_id='iuid-b'") == 0


# 26
def test_legacy_auth_unchanged():
    import inspect
    ru = inspect.getsource(main.request_user_id)
    ra = inspect.getsource(main.require_admin)
    assert "auth_sessions" not in ru and "auth_sessions" not in ra
    assert "X-OneNode-User" in ru


# 27
def test_v2_auth_and_admin_endpoints_present():
    routes = {r.path for r in main.app.routes}
    for p in ("/api/auth/telegram-v2", "/api/auth/max-v2", "/api/auth/email/request-code-v2",
              "/api/auth/email/verify-code-v2", "/api/admin/users-v2",
              "/api/me/profile-v2", "/api/me/devices-v2", "/api/me/sessions-v2", "/api/me/consents-v2"):
        assert p in routes
