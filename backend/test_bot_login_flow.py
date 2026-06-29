from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "bot_login.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    monkeypatch.setattr(main, "APP_ENV", "development")
    monkeypatch.setattr(main, "TELEGRAM_BOT_USERNAME", "OneNodeTestBot")
    monkeypatch.setattr(main, "MAX_BOT_DEEP_LINK_BASE", "https://max.ru/onenode-test")
    main.init_db()
    return db_file


def _login_token(deep_link: str) -> str:
    parsed = urlparse(deep_link)
    payload = parse_qs(parsed.query).get("start", [""])[0]
    assert payload.startswith("login_")
    return payload.replace("login_", "", 1)


def test_plain_start_returns_welcome_and_button(temp_db):
    answer = main.bot_command_response("telegram", "/start")
    assert "Добро пожаловать" in answer["text"]
    assert answer["buttons"][0]["text"] == "Открыть приложение"


def test_bot_login_start_creates_challenge_and_cookie(temp_db):
    client = TestClient(main.app)
    response = client.post("/api/auth/bot-login/start", json={"provider": "telegram"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["deep_link"].startswith("https://t.me/OneNodeTestBot?start=login_")
    assert payload["poll_interval_ms"] == 2000
    assert main.BOT_LOGIN_CHALLENGE_COOKIE_NAME in client.cookies
    with main.db() as conn:
        row = conn.execute("SELECT provider, status, token_hash FROM auth_login_challenges").fetchone()
    assert row["provider"] == "telegram"
    assert row["status"] == "pending"
    assert "login_" not in row["token_hash"]


def test_auth_capabilities_report_bot_login_availability(temp_db):
    client = TestClient(main.app)
    payload = client.get("/api/auth/capabilities-v2").json()
    assert payload["password_login_available"] is True
    assert payload["password_register_available"] is True
    assert payload["email_otp_available"] is False
    assert payload["bot_login"]["telegram_bot_login_available"] is True
    assert payload["bot_login"]["max_bot_login_available"] is True


def test_bot_login_start_without_provider_config_returns_503(temp_db, monkeypatch):
    monkeypatch.setattr(main, "TELEGRAM_BOT_USERNAME", "")
    monkeypatch.setattr(main, "TELEGRAM_BOT_DEEP_LINK_BASE", "")
    client = TestClient(main.app)
    response = client.post("/api/auth/bot-login/start", json={"provider": "telegram"})
    assert response.status_code == 503
    assert response.json()["detail"] == "provider_not_configured"
    assert main.BOT_LOGIN_CHALLENGE_COOKIE_NAME not in client.cookies
    with main.db() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM auth_login_challenges").fetchone()["c"]
    assert count == 0


def test_bot_login_capabilities_false_without_deep_link_config(temp_db, monkeypatch):
    monkeypatch.setattr(main, "TELEGRAM_BOT_USERNAME", "")
    monkeypatch.setattr(main, "TELEGRAM_BOT_DEEP_LINK_BASE", "")
    monkeypatch.setattr(main, "MAX_BOT_DEEP_LINK_BASE", "")
    client = TestClient(main.app)
    payload = client.get("/api/auth/capabilities-v2").json()
    assert payload["bot_login"]["telegram_bot_login_available"] is False
    assert payload["bot_login"]["max_bot_login_available"] is False


def test_bot_login_status_without_cookie_does_not_create_session(temp_db):
    client = TestClient(main.app)
    response = client.get("/api/auth/bot-login/status")
    assert response.status_code == 401
    assert main.TRUSTED_SESSION_COOKIE_NAME not in client.cookies


def test_telegram_start_login_only_shows_confirmation(temp_db):
    client = TestClient(main.app)
    started = client.post("/api/auth/bot-login/start", json={"provider": "telegram"}).json()
    token = _login_token(started["deep_link"])

    answer = main.bot_command_response("telegram", f"/start login_{token}")
    assert "Подтвердите вход" in answer["text"]
    assert answer["buttons"][0]["callback_data"] == f"approve:login_{token}"
    assert client.get("/api/auth/bot-login/status").json()["status"] == "pending"
    assert main.TRUSTED_SESSION_COOKIE_NAME not in client.cookies


def test_telegram_callback_approve_then_status_creates_session(temp_db, monkeypatch):
    async def fake_telegram_api(method: str, payload: dict | None = None) -> dict:
        return {"ok": True, "result": {"method": method, "payload": payload}}

    monkeypatch.setattr(main, "telegram_api", fake_telegram_api)
    client = TestClient(main.app)
    started = client.post("/api/auth/bot-login/start", json={"provider": "telegram"}).json()
    token = _login_token(started["deep_link"])

    result = asyncio.run(main.handle_telegram_update({
        "update_id": 1,
        "callback_query": {
            "id": "cb1",
            "data": f"approve:login_{token}",
            "from": {"id": 777, "username": "tg_user", "first_name": "T"},
            "message": {"chat": {"id": 777}},
        },
    }, send_replies=True))
    assert result["botLogin"] == "approved"

    status = client.get("/api/auth/bot-login/status")
    assert status.status_code == 200
    assert status.json()["status"] == "authenticated"
    assert main.TRUSTED_SESSION_COOKIE_NAME in client.cookies


def test_max_bot_started_login_then_approve_then_status_creates_session(temp_db, monkeypatch):
    async def fake_max_api(method: str, path: str, payload: dict | None = None, params: dict | None = None) -> dict:
        return {"ok": True, "path": path, "payload": payload, "params": params}

    monkeypatch.setattr(main, "max_api", fake_max_api)
    client = TestClient(main.app)
    started = client.post("/api/auth/bot-login/start", json={"provider": "max"}).json()
    token = _login_token(started["deep_link"])

    shown = asyncio.run(main.handle_max_update({
        "bot_started": {"payload": f"login_{token}", "message": {"sender": {"user_id": "mx-1", "username": "mx_user"}}},
    }, send_replies=True))
    assert shown["answer"]["buttons"][0]["callback_data"] == f"approve:login_{token}"

    approved = asyncio.run(main.handle_max_update({
        "message": {"body": {"text": f"/approve login_{token}"}, "sender": {"user_id": "mx-1", "username": "mx_user"}},
    }, send_replies=True))
    assert approved["botLogin"] == "approved"

    status = client.get("/api/auth/bot-login/status")
    assert status.status_code == 200
    assert status.json()["status"] == "authenticated"
    assert main.TRUSTED_SESSION_COOKIE_NAME in client.cookies


def test_expired_challenge_cannot_authenticate(temp_db):
    client = TestClient(main.app)
    client.post("/api/auth/bot-login/start", json={"provider": "telegram"})
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with main.db() as conn:
        conn.execute("UPDATE auth_login_challenges SET expires_at = ?", (past,))
    response = client.get("/api/auth/bot-login/status")
    assert response.status_code == 200
    assert response.json()["status"] == "expired"
    assert main.TRUSTED_SESSION_COOKIE_NAME not in client.cookies


def test_consumed_challenge_cannot_be_reused(temp_db):
    client = TestClient(main.app)
    started = client.post("/api/auth/bot-login/start", json={"provider": "telegram"}).json()
    challenge_cookie = client.cookies.get(main.BOT_LOGIN_CHALLENGE_COOKIE_NAME)
    token = _login_token(started["deep_link"])
    assert main.approve_bot_login_challenge("telegram", token, {"id": 888, "username": "once"})
    assert client.get("/api/auth/bot-login/status").json()["status"] == "authenticated"
    client.cookies.set(main.BOT_LOGIN_CHALLENGE_COOKIE_NAME, challenge_cookie)
    reused = client.get("/api/auth/bot-login/status")
    assert reused.status_code == 409


def test_client_userid_or_username_does_not_create_session(temp_db):
    client = TestClient(main.app)
    response = client.post("/api/auth/bot-login/start", json={"provider": "telegram", "userId": "telegram_1", "username": "fake"})
    assert response.status_code == 200
    status = client.get("/api/auth/bot-login/status")
    assert status.status_code == 200
    assert status.json()["status"] == "pending"
    assert main.TRUSTED_SESSION_COOKIE_NAME not in client.cookies
