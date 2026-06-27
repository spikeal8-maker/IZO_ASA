"""Bootstrap-v2 tests (Phase 5).

Anonymous initialization endpoint. All tests use a TEMPORARY SQLite file via
monkeypatching main.DB_PATH; the working DB backend/onenode.sqlite3 is never touched.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "bootstrap_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    main.init_db()
    return db_file


def count(table, where="", params=()):
    with main.db() as conn:
        return conn.execute(f"SELECT COUNT(*) AS c FROM {table} {where}", params).fetchone()["c"]


def post(client, body=None, headers=None, cookies=None):
    return client.post("/api/auth/bootstrap-v2", json=body or {}, headers=headers, cookies=cookies)


# 1
def test_missing_installation_id_is_generated(temp_db):
    with TestClient(main.app) as client:
        r = post(client, {"platform": "web_desktop"})
    assert r.status_code == 200
    assert r.json()["installation_id"]


# 2
def test_missing_anonymous_id_is_generated(temp_db):
    with TestClient(main.app) as client:
        r = post(client, {"platform": "web_desktop"})
    assert r.json()["anonymous_id"]


# 3
def test_does_not_create_users(temp_db):
    before = count("users")
    with TestClient(main.app) as client:
        post(client, {"platform": "web_mobile"})
    assert count("users") == before


# 4
def test_does_not_create_auth_identities(temp_db):
    with TestClient(main.app) as client:
        post(client, {"platform": "web_mobile"})
    assert count("auth_identities") == 0


# 5
def test_does_not_create_auth_sessions(temp_db):
    with TestClient(main.app) as client:
        post(client, {"platform": "web_mobile"})
    assert count("auth_sessions") == 0


# 6
def test_creates_device_installation_row(temp_db):
    with TestClient(main.app) as client:
        r = post(client, {"platform": "pwa", "installation_id": "inst-1"})
    assert count("device_installations", "WHERE installation_id = 'inst-1'") == 1
    with main.db() as conn:
        row = conn.execute("SELECT * FROM device_installations WHERE installation_id='inst-1'").fetchone()
    assert row["internal_user_id"] is None
    assert row["legacy_user_id"] is None
    assert row["platform"] == "pwa"
    assert row["storage_type"] == "local_storage"
    assert row["metadata_json"]


# 7
def test_repeated_same_installation_updates_not_duplicates(temp_db):
    with TestClient(main.app) as client:
        r1 = post(client, {"platform": "web_desktop", "installation_id": "inst-x"})
        first_seen = None
        with main.db() as conn:
            row1 = conn.execute("SELECT first_seen_at, last_seen_at, anonymous_id FROM device_installations WHERE installation_id='inst-x'").fetchone()
        r2 = post(client, {"platform": "web_mobile", "installation_id": "inst-x"})
    assert count("device_installations", "WHERE installation_id='inst-x'") == 1
    with main.db() as conn:
        row2 = conn.execute("SELECT first_seen_at, last_seen_at, platform, anonymous_id FROM device_installations WHERE installation_id='inst-x'").fetchone()
    # first_seen unchanged, last_seen advanced, platform updated, anonymous_id stable
    assert row2["first_seen_at"] == row1["first_seen_at"]
    assert row2["last_seen_at"] >= row1["last_seen_at"]
    assert row2["platform"] == "web_mobile"
    assert r2.json()["anonymous_id"] == row1["anonymous_id"]


# 8
def test_body_identity_fields_are_ignored(temp_db):
    with TestClient(main.app) as client:
        r = post(client, {
            "platform": "web_desktop",
            "installation_id": "inst-id8",
            "user_id": "admin",
            "internal_user_id": "iuid-injected",
            "legacy_user_id": "telegram_999",
            "role": "admin",
            "admin": True,
        })
    assert r.status_code == 200
    assert r.json()["is_authenticated"] is False
    with main.db() as conn:
        row = conn.execute("SELECT internal_user_id, legacy_user_id FROM device_installations WHERE installation_id='inst-id8'").fetchone()
    assert row["internal_user_id"] is None
    assert row["legacy_user_id"] is None
    # no user created from injected identity
    assert count("users", "WHERE id='admin'") == 0


# 9
def test_x_onenode_user_header_is_ignored(temp_db):
    with TestClient(main.app) as client:
        r = post(client, {"platform": "web_desktop"}, headers={"X-OneNode-User": "admin"})
    assert r.status_code == 200
    assert r.json()["is_authenticated"] is False
    assert count("users", "WHERE id='admin'") == 0


# 10
def test_onenode_user_cookie_is_ignored(temp_db):
    with TestClient(main.app) as client:
        client.cookies.set("onenode_user", "admin")
        r = post(client, {"platform": "web_desktop"})
    assert r.status_code == 200
    assert r.json()["is_authenticated"] is False


# 11
def test_is_authenticated_false(temp_db):
    with TestClient(main.app) as client:
        r = post(client, {"platform": "telegram_mini_app"})
    assert r.json()["is_authenticated"] is False


# 12
def test_response_contains_required_consents(temp_db):
    with TestClient(main.app) as client:
        r = post(client, {"platform": "web_desktop"})
    consents = r.json()["required_consents"]
    for c in ["terms", "privacy", "personal_data_processing", "cookies"]:
        assert c in consents


# 13
def test_response_contains_auth_methods(temp_db):
    with TestClient(main.app) as client:
        tg = post(client, {"platform": "telegram_mini_app"}).json()
        mx = post(client, {"platform": "max_mini_app"}).json()
        web = post(client, {"platform": "web_desktop"}).json()
    assert "telegram" in tg["auth_methods"] and "email_otp" in tg["auth_methods"]
    assert "max" in mx["auth_methods"] and "email_otp" in mx["auth_methods"]
    assert web["auth_methods"] == ["email_otp"]


# 14 (Phase 5.1) — event_logs now exists and bootstrap still succeeds.
def test_event_logs_table_exists(temp_db):
    with main.db() as conn:
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "event_logs" in tables
    with TestClient(main.app) as client:
        r = post(client, {"platform": "web_desktop"})
    assert r.status_code == 200


# server_time present and ISO-like
def test_server_time_present(temp_db):
    with TestClient(main.app) as client:
        r = post(client, {"platform": "unknown"})
    assert "T" in r.json()["server_time"]


# metadata captures client + utm summary
def test_metadata_captures_client_and_utm(temp_db):
    body = {
        "platform": "web_desktop",
        "installation_id": "inst-meta",
        "client": {"language": "ru", "timezone": "Europe/Moscow", "screen_width": 1440},
        "utm": {"source": "tg", "medium": "cpc", "campaign": "spring"},
    }
    with TestClient(main.app) as client:
        post(client, body)
    import json as _json
    with main.db() as conn:
        meta = _json.loads(conn.execute("SELECT metadata_json FROM device_installations WHERE installation_id='inst-meta'").fetchone()["metadata_json"])
    assert meta["client"]["language"] == "ru"
    assert meta["utm"]["source"] == "tg"


# ---------------------------------------------------------------------------
# Phase 5.1: event_logs + app_opened
# ---------------------------------------------------------------------------
import json as _json


def get_app_opened(installation_id):
    with main.db() as conn:
        return conn.execute(
            "SELECT * FROM event_logs WHERE event_name='app_opened' AND installation_id=?",
            (installation_id,),
        ).fetchall()


# 1
def test_init_db_creates_event_logs_table(temp_db):
    with main.db() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(event_logs)")}
    expected = {
        "id", "internal_user_id", "legacy_user_id", "anonymous_id", "installation_id",
        "session_id", "event_name", "platform", "device_type", "ip_address",
        "user_agent_hash", "properties_json", "created_at",
    }
    assert expected <= cols


# 2
def test_init_db_idempotent_with_event_logs(temp_db):
    main.init_db()
    main.init_db()  # must not raise
    with main.db() as conn:
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "event_logs" in tables


# 3,4,5,6
def test_bootstrap_writes_app_opened_event(temp_db):
    with TestClient(main.app) as client:
        r = post(client, {"platform": "telegram_mini_app", "installation_id": "inst-evt"})
    body = r.json()
    rows = get_app_opened("inst-evt")
    assert len(rows) == 1
    ev = rows[0]
    assert ev["anonymous_id"] == body["anonymous_id"]      # 4
    assert ev["installation_id"] == "inst-evt"              # 5
    assert ev["platform"] == "telegram_mini_app"           # 6
    props = _json.loads(ev["properties_json"])
    assert props["auth_methods"] == body["auth_methods"]
    assert props["required_consents"] == body["required_consents"]
    assert props["has_installation_id_from_client"] is True
    assert props["has_anonymous_id_from_client"] is False


# 7
def test_app_opened_does_not_create_user(temp_db):
    before = count("users")
    with TestClient(main.app) as client:
        post(client, {"platform": "web_desktop"})
    assert count("users") == before


# 8
def test_app_opened_does_not_create_session(temp_db):
    with TestClient(main.app) as client:
        post(client, {"platform": "web_desktop"})
    assert count("auth_sessions") == 0


# 9,10,11 — no Authorization header, cookies, or raw tokens stored
def test_app_opened_does_not_store_sensitive_data(temp_db):
    secret_auth = "Bearer super-secret-access-token"
    secret_cookie = "onenode_session=raw-session-value; onenode_user=admin"
    with TestClient(main.app) as client:
        client.cookies.set("onenode_user", "admin")
        post(
            client,
            {"platform": "web_desktop", "installation_id": "inst-sec"},
            headers={"Authorization": secret_auth},
        )
    with main.db() as conn:
        row = conn.execute("SELECT * FROM event_logs WHERE installation_id='inst-sec'").fetchone()
    blob = " ".join(str(v) for v in tuple(row))
    assert "super-secret-access-token" not in blob   # Authorization not stored
    assert "raw-session-value" not in blob            # no raw tokens
    assert secret_cookie not in blob                  # cookies not stored
    assert "admin" not in blob                         # legacy cookie identity not stored
    # ip/user_agent columns must never hold a raw UA or auth material
    assert row["user_agent_hash"] is None or len(row["user_agent_hash"]) == 64


# 12
def test_repeated_bootstrap_writes_another_event_no_device_dup(temp_db):
    with TestClient(main.app) as client:
        post(client, {"platform": "web_desktop", "installation_id": "inst-rep"})
        post(client, {"platform": "web_mobile", "installation_id": "inst-rep"})
    assert len(get_app_opened("inst-rep")) == 2
    assert count("device_installations", "WHERE installation_id='inst-rep'") == 1
