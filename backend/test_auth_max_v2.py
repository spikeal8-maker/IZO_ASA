"""MAX auth v2 (strict) tests (Phase 7).

Signatures are NEVER mocked: every "valid" fixture is real MAX WebAppData signed
with a known test bot token using the official algorithm
  secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
  hash       = HMAC_SHA256(key=secret_key, msg=launch_params)
All tests use a TEMPORARY SQLite DB via monkeypatching main.DB_PATH.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from test_support.browser_client import BrowserTestClient

import main


TEST_BOT_TOKEN = "max-987654:TEST-bot-token-for-unit-tests"


def sign_web_app_data(fields: dict[str, str], token: str = TEST_BOT_TOKEN) -> str:
    launch_params = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret_key, launch_params.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": h})


def make_web_app_data(user=None, auth_date=None, include_auth_date=True, include_user=True, token=TEST_BOT_TOKEN, extra=None):
    user = user or {"id": 700800900, "first_name": "Max", "username": "max_user", "language_code": "ru"}
    fields = {}
    if include_auth_date:
        fields["auth_date"] = str(auth_date if auth_date is not None else int(time.time()))
    if include_user:
        fields["user"] = json.dumps(user, separators=(",", ":"))
    fields["query_id"] = "MAX-test"
    if extra:
        fields.update(extra)
    return sign_web_app_data(fields, token)


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "max_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "MAX_BOT_TOKEN", TEST_BOT_TOKEN)
    monkeypatch.setattr(main, "MAX_WEB_APP_DATA_TTL_SECONDS", 86400)
    main.init_db()
    return db_file


def count(table, where="", params=()):
    with main.db() as conn:
        return conn.execute(f"SELECT COUNT(*) AS c FROM {table} {where}", params).fetchone()["c"]


def post(client, web_app_data=None, **body):
    payload = {"platform": "max_mini_app"}
    if web_app_data is not None:
        payload["web_app_data"] = web_app_data
    payload.update(body)
    return client.post("/api/auth/max-v2", json=payload)


# 1
def test_valid_login_returns_session_tokens(temp_db):
    with BrowserTestClient(main.app) as client:
        r = post(client, make_web_app_data())
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["session_token"] and b["refresh_token"]
    assert b["expires_at"] and b["refresh_expires_at"]
    assert b["internal_user_id"] and b["legacy_user_id"]
    assert b["profile_completed"] is False
    assert b["required_consents"] == []


# 2
def test_valid_login_creates_max_identity(temp_db):
    with BrowserTestClient(main.app) as client:
        post(client, make_web_app_data(user={"id": 555, "first_name": "Bo"}))
    with main.db() as conn:
        row = conn.execute("SELECT * FROM auth_identities WHERE provider='max' AND provider_user_id='555'").fetchone()
    assert row is not None
    assert row["verified_at"] is not None
    assert row["internal_user_id"]


# 3
def test_session_created_with_hashes_only(temp_db):
    with BrowserTestClient(main.app) as client:
        r = post(client, make_web_app_data())
    b = r.json()
    with main.db() as conn:
        row = conn.execute("SELECT * FROM auth_sessions").fetchone()
    assert row["session_token_hash"] == main.hash_token(b["session_token"])
    blob = " ".join(str(v) for v in tuple(row))
    assert b["session_token"] not in blob
    assert b["refresh_token"] not in blob


# 4 & 5
def test_repeated_login_reuses_internal_id_no_dup(temp_db):
    with BrowserTestClient(main.app) as client:
        r1 = post(client, make_web_app_data(user={"id": 777, "first_name": "C"}))
        r2 = post(client, make_web_app_data(user={"id": 777, "first_name": "C2"}))
    assert r1.json()["internal_user_id"] == r2.json()["internal_user_id"]
    assert count("auth_identities", "WHERE provider='max' AND provider_user_id='777'") == 1


# 6
def test_login_links_existing_legacy_user(temp_db):
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, max_id, internal_user_id, language, role, created_at, last_login_at) "
            "VALUES ('max_999', '999', 'legacy-iuid-max', 'ru', 'user', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
    with BrowserTestClient(main.app) as client:
        r = post(client, make_web_app_data(user={"id": 999, "first_name": "Leg"}))
    b = r.json()
    assert b["legacy_user_id"] == "max_999"
    assert b["internal_user_id"] == "legacy-iuid-max"
    assert count("users", "WHERE id='max_999'") == 1


# 7
def test_login_creates_new_user_when_no_legacy(temp_db):
    before = count("users")
    with BrowserTestClient(main.app) as client:
        r = post(client, make_web_app_data(user={"id": 4242, "first_name": "New"}))
    assert count("users") == before + 1
    assert r.json()["legacy_user_id"] == "max_4242"


# 8
def test_missing_web_app_data_returns_401(temp_db):
    with BrowserTestClient(main.app) as client:
        r = post(client, web_app_data="")
    assert r.status_code == 401


# 9
def test_missing_hash_returns_401(temp_db):
    fields = {"auth_date": str(int(time.time())), "user": json.dumps({"id": 1, "first_name": "A"}), "query_id": "x"}
    no_hash = urlencode(fields)  # no hash key at all
    with BrowserTestClient(main.app) as client:
        r = post(client, no_hash)
    assert r.status_code == 401


# 10
def test_duplicate_hash_returns_401(temp_db):
    signed = make_web_app_data()
    dup = signed + "&hash=deadbeef"
    with BrowserTestClient(main.app) as client:
        r = post(client, dup)
    assert r.status_code == 401


# 11
def test_invalid_signature_returns_401(temp_db):
    good = make_web_app_data()
    tampered = good[:-1] + ("0" if good[-1] != "0" else "1")
    with BrowserTestClient(main.app) as client:
        r = post(client, tampered)
    assert r.status_code == 401


# 12
def test_expired_auth_date_returns_401(temp_db):
    stale = make_web_app_data(auth_date=int(time.time()) - 90000)
    with BrowserTestClient(main.app) as client:
        r = post(client, stale)
    assert r.status_code == 401
    assert count("security_events", "WHERE event_type='expired_init_data'") == 1


# 13
def test_missing_auth_date_returns_401(temp_db):
    data = make_web_app_data(include_auth_date=False)
    with BrowserTestClient(main.app) as client:
        r = post(client, data)
    assert r.status_code == 401
    assert count("security_events", "WHERE event_type='max_auth_date_missing'") == 1


# 14
def test_missing_user_returns_401(temp_db):
    data = make_web_app_data(include_user=False)
    with BrowserTestClient(main.app) as client:
        r = post(client, data)
    assert r.status_code == 401
    assert count("security_events", "WHERE event_type='max_user_missing'") == 1


# 15
def test_frontend_user_id_in_body_ignored(temp_db):
    with BrowserTestClient(main.app) as client:
        r = post(client, make_web_app_data(user={"id": 100, "first_name": "Real"}),
                 user_id="admin", internal_user_id="iuid-injected", legacy_user_id="max_admin", role="admin")
    b = r.json()
    assert b["internal_user_id"] != "iuid-injected"
    assert b["legacy_user_id"] == "max_100"


# 16
def test_x_onenode_user_header_ignored(temp_db):
    with BrowserTestClient(main.app) as client:
        r = client.post("/api/auth/max-v2",
                        json={"platform": "max_mini_app", "web_app_data": make_web_app_data(user={"id": 321, "first_name": "H"})},
                        headers={"X-OneNode-User": "admin"})
    assert r.status_code == 200
    assert r.json()["legacy_user_id"] == "max_321"


# 17
def test_onenode_user_cookie_ignored(temp_db):
    with BrowserTestClient(main.app) as client:
        client.cookies.set("onenode_user", "admin")
        r = post(client, make_web_app_data(user={"id": 654, "first_name": "K"}))
    assert r.status_code == 200
    assert r.json()["legacy_user_id"] == "max_654"


# 18
def test_raw_web_app_data_not_stored_in_logs(temp_db):
    web_app_data = make_web_app_data(user={"id": 909, "first_name": "Log"})
    with BrowserTestClient(main.app) as client:
        post(client, web_app_data)
    with main.db() as conn:
        for table in ("event_logs", "security_events", "auth_login_attempts"):
            for row in conn.execute(f"SELECT * FROM {table}").fetchall():
                blob = " ".join(str(v) for v in tuple(row))
                assert web_app_data not in blob
                assert "hash=" not in blob


# 19
def test_raw_tokens_not_stored(temp_db):
    with BrowserTestClient(main.app) as client:
        r = post(client, make_web_app_data())
    b = r.json()
    with main.db() as conn:
        row = conn.execute("SELECT session_token_hash, refresh_token_hash FROM auth_sessions").fetchone()
    assert row["session_token_hash"] != b["session_token"]
    assert row["refresh_token_hash"] != b["refresh_token"]


# 20
def test_security_event_for_invalid_signature(temp_db):
    good = make_web_app_data()
    tampered = good[:-1] + ("0" if good[-1] != "0" else "1")
    with BrowserTestClient(main.app) as client:
        post(client, tampered)
    assert count("security_events", "WHERE event_type='invalid_max_signature'") == 1


# 21
def test_login_attempt_success_row(temp_db):
    with BrowserTestClient(main.app) as client:
        post(client, make_web_app_data(user={"id": 191, "first_name": "S"}))
    assert count("auth_login_attempts", "WHERE provider='max' AND success=1 AND identifier='191'") == 1


# 22
def test_login_attempt_failure_row(temp_db):
    good = make_web_app_data()
    tampered = good[:-1] + ("0" if good[-1] != "0" else "1")
    with BrowserTestClient(main.app) as client:
        post(client, tampered)
    assert count("auth_login_attempts", "WHERE provider='max' AND success=0") == 1


# 23
def test_event_log_login_succeeded(temp_db):
    with BrowserTestClient(main.app) as client:
        post(client, make_web_app_data())
    assert count("event_logs", "WHERE event_name='login_succeeded'") == 1


# 24
def test_event_log_login_failed(temp_db):
    good = make_web_app_data()
    tampered = good[:-1] + ("0" if good[-1] != "0" else "1")
    with BrowserTestClient(main.app) as client:
        post(client, tampered)
    assert count("event_logs", "WHERE event_name='login_failed'") == 1


# 25
def test_device_installation_linked(temp_db):
    with BrowserTestClient(main.app) as client:
        r = post(client, make_web_app_data(user={"id": 818, "first_name": "D"}), installation_id="inst-max-1", anonymous_id="anon-1")
    iuid = r.json()["internal_user_id"]
    with main.db() as conn:
        row = conn.execute("SELECT internal_user_id, legacy_user_id FROM device_installations WHERE installation_id='inst-max-1'").fetchone()
    assert row["internal_user_id"] == iuid
    assert row["legacy_user_id"] == "max_818"


# extra: wrong bot token must fail
def test_wrong_bot_token_fails(temp_db):
    forged = make_web_app_data(token="max-000000:WRONG")
    with BrowserTestClient(main.app) as client:
        r = post(client, forged)
    assert r.status_code == 401
    assert count("security_events", "WHERE event_type='invalid_max_signature'") == 1
