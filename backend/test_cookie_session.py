"""HttpOnly trusted-session cookie tests (Phase 13).

All tests use a TEMPORARY SQLite DB via monkeypatching main.DB_PATH;
backend/onenode.sqlite3 is never touched.
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


TG_TOKEN = "13579:TEST-tg-token"
MAX_TOKEN = "max-2468:TEST-max-token"
# AUTH-LEGACY-001B: browsers always send Origin on unsafe methods; cookie-auth
# mutations must present an allowlisted Origin to pass the CSRF boundary.
BROWSER_ORIGIN = {"Origin": "https://izo.alikinas.ru"}


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "cookie_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", TG_TOKEN)
    monkeypatch.setattr(main, "TELEGRAM_INIT_DATA_TTL_SECONDS", 86400)
    monkeypatch.setattr(main, "MAX_BOT_TOKEN", MAX_TOKEN)
    monkeypatch.setattr(main, "MAX_WEB_APP_DATA_TTL_SECONDS", 86400)
    monkeypatch.setattr(main, "APP_ENV", "development")
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SAMESITE", "lax")
    monkeypatch.setattr(main, "SESSION_ACCESS_TTL_SECONDS", 3600)
    monkeypatch.setattr(main, "SESSION_REFRESH_TTL_SECONDS", 2592000)
    main.init_db()
    return db_file


def sign(fields, token, key=b"WebAppData"):
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(key, token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": h})


def tg_init_data(uid=111):
    return sign({"auth_date": str(int(time.time())), "user": json.dumps({"id": uid, "first_name": "T"})}, TG_TOKEN)


def max_web_app_data(uid=222):
    return sign({"auth_date": str(int(time.time())), "user": json.dumps({"id": uid, "first_name": "M"})}, MAX_TOKEN)


def set_cookie_headers(resp):
    return resp.headers.get_list("set-cookie") if hasattr(resp.headers, "get_list") else resp.headers.get("set-cookie", "").split(", ")


def find_cookie(resp, name):
    for sc in set_cookie_headers(resp):
        if sc.startswith(name + "="):
            return sc
    return None


# 1
def test_telegram_sets_httponly_cookies(temp_db):
    with BrowserTestClient(main.app) as client:
        r = client.post("/api/auth/telegram-v2", json={"init_data": tg_init_data(), "platform": "telegram_mini_app"})
    assert r.status_code == 200
    s = find_cookie(r, "onenode_session")
    rf = find_cookie(r, "onenode_refresh")
    assert s and rf
    assert "httponly" in s.lower() and "httponly" in rf.lower()


# 2
def test_max_sets_httponly_cookies(temp_db):
    with BrowserTestClient(main.app) as client:
        r = client.post("/api/auth/max-v2", json={"web_app_data": max_web_app_data(), "platform": "max_mini_app"})
    assert r.status_code == 200
    assert "httponly" in (find_cookie(r, "onenode_session") or "").lower()
    assert "httponly" in (find_cookie(r, "onenode_refresh") or "").lower()


# 3
def test_email_verify_sets_httponly_cookies(temp_db, monkeypatch):
    monkeypatch.setattr(main, "EMAIL_OTP_DEBUG_RETURN_CODE", True)
    with BrowserTestClient(main.app) as client:
        req = client.post("/api/auth/email/request-code-v2", json={"email": "c@example.com", "platform": "web_desktop"})
        code = req.json()["debug_code"]
        r = client.post("/api/auth/email/verify-code-v2", json={"challenge_id": req.json()["challenge_id"], "code": code, "platform": "web_desktop"})
    assert r.status_code == 200
    assert "httponly" in (find_cookie(r, "onenode_session") or "").lower()
    assert "httponly" in (find_cookie(r, "onenode_refresh") or "").lower()


# 4, 6
def test_cookies_httponly_and_samesite(temp_db):
    with BrowserTestClient(main.app) as client:
        r = client.post("/api/auth/telegram-v2", json={"init_data": tg_init_data(), "platform": "telegram_mini_app"})
    s = find_cookie(r, "onenode_session").lower()
    assert "httponly" in s
    assert "samesite=lax" in s


# 5
def test_secure_in_production_config(temp_db, monkeypatch):
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", True)
    with BrowserTestClient(main.app) as client:
        r = client.post("/api/auth/telegram-v2", json={"init_data": tg_init_data(), "platform": "telegram_mini_app"})
    assert "secure" in find_cookie(r, "onenode_session").lower()
    assert "secure" in find_cookie(r, "onenode_refresh").lower()


# 7, 8
def test_cookie_max_age_matches_ttls(temp_db):
    with BrowserTestClient(main.app) as client:
        r = client.post("/api/auth/telegram-v2", json={"init_data": tg_init_data(), "platform": "telegram_mini_app"})
    s = find_cookie(r, "onenode_session").lower()
    rf = find_cookie(r, "onenode_refresh").lower()
    assert "max-age=3600" in s
    assert "max-age=2592000" in rf


# 9
def test_refresh_uses_cookie_when_body_missing(temp_db):
    with BrowserTestClient(main.app) as client:
        client.post("/api/auth/telegram-v2", json={"init_data": tg_init_data(), "platform": "telegram_mini_app"})
        # refresh cookie now stored in the client; send empty body
        r = client.post("/api/auth/session/refresh-v2", json={})
    assert r.status_code == 200
    assert r.json()["session_token"]


# 10
def test_refresh_rotates_cookies(temp_db):
    with BrowserTestClient(main.app) as client:
        client.post("/api/auth/telegram-v2", json={"init_data": tg_init_data(), "platform": "telegram_mini_app"})
        old_refresh = client.cookies.get("onenode_refresh")
        r = client.post("/api/auth/session/refresh-v2", json={})
        new_refresh = client.cookies.get("onenode_refresh")
    assert r.status_code == 200
    assert new_refresh and new_refresh != old_refresh


# 11
def test_old_refresh_cookie_cannot_be_reused(temp_db):
    with BrowserTestClient(main.app) as client:
        login = client.post("/api/auth/telegram-v2", json={"init_data": tg_init_data(), "platform": "telegram_mini_app"})
        old_refresh = login.json()["refresh_token"]
        first = client.post("/api/auth/session/refresh-v2", json={})
        assert first.status_code == 200
        reuse = client.post("/api/auth/session/refresh-v2", json={"refresh_token": old_refresh})
    assert reuse.status_code == 401


# 12, 13
def test_logout_clears_cookies_using_cookie(temp_db):
    with BrowserTestClient(main.app) as client:
        client.post("/api/auth/telegram-v2", json={"init_data": tg_init_data(), "platform": "telegram_mini_app"})
        # logout with empty body -> uses session cookie
        r = client.post("/api/auth/session/logout-v2", json={})
        assert r.status_code == 200 and r.json()["ok"] is True
        # Set-Cookie clears both (max-age=0 / empty value)
        cleared = " ".join(set_cookie_headers(r)).lower()
        assert "onenode_session=" in cleared and "onenode_refresh=" in cleared
        # session is revoked -> me-v2 now 401
        me = client.get("/api/me-v2")
    assert me.status_code == 401


# 14
def test_resolve_accepts_trusted_cookie(temp_db):
    with BrowserTestClient(main.app) as client:
        client.post("/api/auth/telegram-v2", json={"init_data": tg_init_data(uid=900), "platform": "telegram_mini_app"})
        # no Authorization header; cookie alone authenticates
        me = client.get("/api/me-v2")
    assert me.status_code == 200
    assert me.json()["legacy_user_id"] == "telegram_900"


# 15
def test_resolve_ignores_legacy_onenode_user(temp_db):
    with BrowserTestClient(main.app) as client:
        client.cookies.set("onenode_user", "telegram_900")  # legacy cookie, must be ignored
        me = client.get("/api/me-v2")
    assert me.status_code == 401


# 16, 17
def test_raw_tokens_not_stored_cookies_not_logged(temp_db):
    with BrowserTestClient(main.app) as client:
        r = client.post("/api/auth/telegram-v2", json={"init_data": tg_init_data(uid=42), "platform": "telegram_mini_app"})
    body = r.json()
    with main.db() as conn:
        row = conn.execute("SELECT * FROM auth_sessions").fetchone()
    blob = " ".join(str(v) for v in tuple(row))
    assert body["session_token"] not in blob
    assert body["refresh_token"] not in blob
    assert row["session_token_hash"] == main.hash_token(body["session_token"])
    # event_logs / security_events never carry raw token or cookie values
    with main.db() as conn:
        for table in ("event_logs", "security_events", "auth_login_attempts"):
            for r2 in conn.execute(f"SELECT * FROM {table}").fetchall():
                b = " ".join(str(v) for v in tuple(r2))
                assert body["session_token"] not in b and body["refresh_token"] not in b
