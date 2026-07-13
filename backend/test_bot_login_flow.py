from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

import main


def _reset_max_deep_link_cache() -> None:
    main._MAX_BOT_DEEP_LINK_CACHE.update({
        "attempted": False,
        "base": None,
        "source": "unresolved",
        "resolved": False,
        "api_status": None,
        "fields": [],
    })


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "bot_login.sqlite3"
    _reset_max_deep_link_cache()
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    monkeypatch.setattr(main, "APP_ENV", "development")
    monkeypatch.setattr(main, "TELEGRAM_BOT_USERNAME", "OneNodeTestBot")
    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "test-telegram-token")
    monkeypatch.setattr(main, "MAX_BOT_TOKEN", "test-max-token")
    monkeypatch.setattr(main, "MAX_BOT_DEEP_LINK_BASE", "https://max.ru/onenode-test")
    main.init_db()
    yield db_file
    _reset_max_deep_link_cache()


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
    monkeypatch.setattr(main, "MAX_BOT_TOKEN", "")
    _reset_max_deep_link_cache()
    client = TestClient(main.app)
    payload = client.get("/api/auth/capabilities-v2").json()
    assert payload["bot_login"]["telegram_bot_login_available"] is False
    assert payload["bot_login"]["max_bot_login_available"] is False


def test_max_capability_true_when_explicit_deep_link_base_exists(temp_db):
    client = TestClient(main.app)
    payload = client.get("/api/auth/capabilities-v2").json()
    assert payload["bot_login"]["max_bot_login_available"] is True


class _FakeMaxResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._payload


class _FakeMaxClient:
    calls: list[dict] = []
    response = _FakeMaxResponse(200, {"username": "real_max_bot"})
    verify = None

    def __init__(self, timeout: int = 10, verify=None):
        self.timeout = timeout
        type(self).verify = verify

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url: str, headers: dict | None = None):
        self.calls.append({"url": url, "headers": dict(headers or {})})
        return self.response


def test_max_capability_resolves_deep_link_base_from_api_me(temp_db, monkeypatch, capsys):
    monkeypatch.setattr(main, "MAX_BOT_DEEP_LINK_BASE", "")
    monkeypatch.setattr(main, "MAX_BOT_TOKEN", "secret-max-token")
    monkeypatch.setattr(main.httpx, "Client", _FakeMaxClient)
    _FakeMaxClient.calls = []
    _FakeMaxClient.response = _FakeMaxResponse(200, {"username": "real_max_bot"})
    _reset_max_deep_link_cache()

    payload = TestClient(main.app).get("/api/auth/capabilities-v2").json()

    assert payload["bot_login"]["max_bot_login_available"] is True
    assert main._MAX_BOT_DEEP_LINK_CACHE["source"] == "api"
    assert main._MAX_BOT_DEEP_LINK_CACHE["base"] == "https://max.ru/real_max_bot"
    assert _FakeMaxClient.verify is main.MAX_HTTP_VERIFY
    assert _FakeMaxClient.calls[0]["url"].endswith("/me")
    assert "secret-max-token" not in capsys.readouterr().out


def test_max_capability_false_when_api_me_has_no_nickname(temp_db, monkeypatch, capsys):
    monkeypatch.setattr(main, "MAX_BOT_DEEP_LINK_BASE", "")
    monkeypatch.setattr(main, "MAX_BOT_TOKEN", "secret-max-token")
    monkeypatch.setattr(main.httpx, "Client", _FakeMaxClient)
    _FakeMaxClient.calls = []
    _FakeMaxClient.response = _FakeMaxResponse(200, {"id": "bot-1", "name": "No public nickname"})
    _reset_max_deep_link_cache()

    payload = TestClient(main.app).get("/api/auth/capabilities-v2").json()

    assert payload["bot_login"]["max_bot_login_available"] is False
    assert main._MAX_BOT_DEEP_LINK_CACHE["source"] == "failed"
    output = capsys.readouterr().out
    assert "secret-max-token" not in output
    assert "fields=" in output


def test_max_bot_login_start_resolves_api_deep_link_without_token_leak(temp_db, monkeypatch, capsys):
    monkeypatch.setattr(main, "MAX_BOT_DEEP_LINK_BASE", "")
    monkeypatch.setattr(main, "MAX_BOT_TOKEN", "secret-max-token")
    monkeypatch.setattr(main.httpx, "Client", _FakeMaxClient)
    _FakeMaxClient.calls = []
    _FakeMaxClient.response = _FakeMaxResponse(200, {"bot": {"username": "real_max_bot"}})
    _reset_max_deep_link_cache()

    response = TestClient(main.app).post("/api/auth/bot-login/start", json={"provider": "max"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["deep_link"].startswith("https://max.ru/real_max_bot?start=login_")
    assert "secret-max-token" not in response.text
    assert "secret-max-token" not in capsys.readouterr().out


def test_max_deep_link_rejects_payload_over_limit(temp_db):
    token = "x" * 128
    with pytest.raises(Exception) as exc:
        main.bot_login_deep_link("max", token)
    assert getattr(exc.value, "detail", "") == "config_error"


def test_bots_status_reports_safe_max_delivery_fields(temp_db):
    payload = TestClient(main.app).get("/api/bots/status").json()
    max_status = payload["max"]
    assert max_status["apiBaseUrl"].startswith("https://")
    assert max_status["mode"] in {"webhook", "polling", "disabled"}
    assert "webhookConfigured" in max_status
    assert "subscriptionStatus" in max_status
    assert "updateTypes" in max_status
    assert "test-max-token" not in str(payload)


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
    assert shown["recipient"] == {"user_id": "mx-1"}

    approved = asyncio.run(main.handle_max_update({
        "message_callback": {
            "payload": f"approve:login_{token}",
            "user": {"user_id": "mx-1", "username": "mx_user"},
            "message": {"recipient": {"user_id": "mx-1"}},
        },
    }, send_replies=True))
    assert approved["botLogin"] == "approved"

    status = client.get("/api/auth/bot-login/status")
    assert status.status_code == 200
    assert status.json()["status"] == "authenticated"
    assert main.TRUSTED_SESSION_COOKIE_NAME in client.cookies


def test_max_message_payload_uses_inline_callback_button(temp_db):
    payload = main.max_message_payload({
        "text": "Подтвердите вход",
        "buttons": [{"text": "Подтвердить вход", "callback_data": "approve:login_test"}],
    })
    assert payload == {
        "text": "Подтвердите вход",
        "attachments": [
            {
                "type": "inline_keyboard",
                "payload": {
                    "buttons": [[{"type": "callback", "text": "Подтвердить вход", "payload": "approve:login_test"}]]
                },
            }
        ],
    }


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
