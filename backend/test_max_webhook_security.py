from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

import main
from app.api.routers import bots_public
from app.security.webhooks import (
    build_max_subscription_payload,
    validate_max_webhook_secret,
)


TEST_SECRET = "Max_Test-Secret_123"
SECRET_HEADER = "X-Max-Bot-Api-Secret"


@pytest.fixture(autouse=True)
def isolated_max_webhook_config(monkeypatch):
    monkeypatch.setattr(main, "MAX_UPDATES_MODE", "webhook")
    monkeypatch.setattr(main, "MAX_BOT_TOKEN", "test-max-token")
    monkeypatch.setattr(main, "MAX_WEBHOOK_SECRET", TEST_SECRET)
    monkeypatch.setattr(bots_public, "MAX_WEBHOOK_MAX_BODY_BYTES", 256)
    main.BOT_RUNTIME.max_polling_diag["lastWebhookAt"] = None
    main.BOT_RUNTIME.max_polling_diag["lastWebhookError"] = None


def test_max_secret_is_required_only_in_webhook_mode():
    validate_max_webhook_secret("polling", "")
    validate_max_webhook_secret("disabled", "")

    with pytest.raises(RuntimeError, match="MAX_WEBHOOK_SECRET is required"):
        validate_max_webhook_secret("webhook", "")
    with pytest.raises(RuntimeError, match="between 5 and 256"):
        validate_max_webhook_secret("webhook", "four")
    with pytest.raises(RuntimeError, match="between 5 and 256"):
        validate_max_webhook_secret("webhook", "a" * 257)
    with pytest.raises(RuntimeError, match="letters, digits, underscore and hyphen"):
        validate_max_webhook_secret("webhook", "not valid")

    validate_max_webhook_secret("webhook", TEST_SECRET)


def test_max_subscription_payload_always_includes_secret():
    assert build_max_subscription_payload(
        "https://example.test/api/max/webhook",
        TEST_SECRET,
        ["bot_started", "message_callback", "message_created"],
    ) == {
        "url": "https://example.test/api/max/webhook",
        "update_types": ["bot_started", "message_callback", "message_created"],
        "secret": TEST_SECRET,
    }


def test_startup_rejects_missing_max_secret_before_database_preflight(monkeypatch):
    monkeypatch.setattr(main, "BOT_UPDATES_MODE", "polling")
    monkeypatch.setattr(main, "TELEGRAM_WEBHOOK_SECRET", "")
    monkeypatch.setattr(main, "MAX_WEBHOOK_SECRET", "")
    database_preflight_called = False

    def unexpected_database_preflight():
        nonlocal database_preflight_called
        database_preflight_called = True

    monkeypatch.setattr(main, "db_guard_preflight", unexpected_database_preflight)

    with pytest.raises(RuntimeError, match="MAX_WEBHOOK_SECRET is required"):
        asyncio.run(main.startup())
    assert database_preflight_called is False


def test_subscription_configuration_sends_validated_secret(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_max_api(method, path, payload=None, params=None):
        captured.update(method=method, path=path, payload=payload, params=params)
        return {"success": True}

    monkeypatch.setattr(main, "MAX_WEBHOOK_URL", "https://example.test/api/max/webhook")
    monkeypatch.setattr(main, "max_api", fake_max_api)

    result = asyncio.run(main.configure_max_webhook_subscription())

    assert result == {"success": True}
    assert captured == {
        "method": "POST",
        "path": "/subscriptions",
        "payload": {
            "url": "https://example.test/api/max/webhook",
            "update_types": ["bot_started", "message_callback", "message_created"],
            "secret": TEST_SECRET,
        },
        "params": None,
    }


def test_polling_mode_disables_max_webhook_receiver(monkeypatch):
    monkeypatch.setattr(main, "MAX_UPDATES_MODE", "polling")
    client = TestClient(main.app)

    response = client.post(
        "/api/max/webhook",
        json={"message": {"body": {"text": "/app"}}},
        headers={SECRET_HEADER: TEST_SECRET},
    )

    assert response.status_code == 404


@pytest.mark.parametrize("header_value", [None, "wrong-secret"])
def test_max_webhook_rejects_missing_or_invalid_secret(header_value, monkeypatch):
    calls: list[dict] = []

    async def fake_handler(payload, send_replies):
        calls.append(payload)

    monkeypatch.setattr(main, "handle_max_update", fake_handler)
    headers = {SECRET_HEADER: header_value} if header_value is not None else {}
    client = TestClient(main.app)

    response = client.post(
        "/api/max/webhook",
        json={"message": {"body": {"text": "/app"}}},
        headers=headers,
    )

    assert response.status_code == 403
    assert calls == []


def test_max_webhook_rejects_runtime_misconfiguration(monkeypatch):
    monkeypatch.setattr(main, "MAX_WEBHOOK_SECRET", "")
    client = TestClient(main.app)

    response = client.post("/api/max/webhook", json={"message": {}})

    assert response.status_code == 503


def test_max_webhook_enforces_body_limit_and_json_object(monkeypatch):
    calls: list[dict] = []

    async def fake_handler(payload, send_replies):
        calls.append(payload)

    monkeypatch.setattr(main, "handle_max_update", fake_handler)
    client = TestClient(main.app)
    headers = {SECRET_HEADER: TEST_SECRET, "Content-Type": "application/json"}

    oversized = client.post(
        "/api/max/webhook",
        content=b"{" + (b" " * 300) + b"}",
        headers=headers,
    )
    malformed = client.post("/api/max/webhook", content=b"[]", headers=headers)

    assert oversized.status_code == 413
    assert malformed.status_code == 400
    assert calls == []


def test_valid_max_update_is_handled_without_logging_secret(monkeypatch, capsys):
    calls: list[tuple[dict, bool]] = []

    async def fake_handler(payload, send_replies):
        calls.append((payload, send_replies))

    monkeypatch.setattr(main, "handle_max_update", fake_handler)
    client = TestClient(main.app)
    payload = {"message": {"body": {"text": "/app"}, "sender": {"user_id": "u1"}}}

    response = client.post(
        "/api/max/webhook",
        json=payload,
        headers={SECRET_HEADER: TEST_SECRET},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls == [(payload, True)]
    assert TEST_SECRET not in capsys.readouterr().out
    assert main.BOT_RUNTIME.max_polling_diag["lastWebhookAt"] is not None


def test_failed_max_update_returns_retryable_status_then_recovers(monkeypatch):
    calls = 0

    async def flaky_handler(payload, send_replies):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary provider failure")

    monkeypatch.setattr(main, "handle_max_update", flaky_handler)
    client = TestClient(main.app)
    payload = {"message": {"body": {"text": "/start"}, "sender": {"user_id": "u1"}}}
    headers = {SECRET_HEADER: TEST_SECRET}

    failed = client.post("/api/max/webhook", json=payload, headers=headers)
    assert failed.status_code == 503
    assert main.BOT_RUNTIME.max_polling_diag["lastWebhookError"] == "RuntimeError"

    retried = client.post("/api/max/webhook", json=payload, headers=headers)
    assert retried.status_code == 200
    assert calls == 2
    assert main.BOT_RUNTIME.max_polling_diag["lastWebhookError"] is None


def test_max_provider_retry_after_post_approval_send_failure_is_idempotent(tmp_path, monkeypatch):
    send_attempts = 0
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "max-retry.sqlite3")
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    monkeypatch.setattr(main, "APP_ENV", "development")
    monkeypatch.setattr(main, "MAX_BOT_DEEP_LINK_BASE", "https://max.ru/onenode-test")
    main.init_db()

    async def flaky_max_api(method, path, payload=None, params=None):
        nonlocal send_attempts
        if method == "POST" and path == "/messages":
            send_attempts += 1
            if send_attempts == 1:
                raise RuntimeError("temporary send failure")
        return {"ok": True}

    monkeypatch.setattr(main, "max_api", flaky_max_api)
    client = TestClient(main.app)
    started = client.post("/api/auth/bot-login/start", json={"provider": "max"}).json()
    payload_value = parse_qs(urlparse(started["deep_link"]).query)["start"][0]
    update = {
        "message_callback": {
            "payload": f"approve:{payload_value}",
            "user": {"user_id": "mx-retry", "username": "mx_retry"},
            "message": {"recipient": {"user_id": "mx-retry"}},
        },
    }
    headers = {SECRET_HEADER: TEST_SECRET}
    provider_client = TestClient(main.app)

    assert provider_client.post("/api/max/webhook", json=update, headers=headers).status_code == 503
    assert provider_client.post("/api/max/webhook", json=update, headers=headers).status_code == 200
    assert send_attempts == 2
    assert client.get("/api/auth/bot-login/status").json()["status"] == "authenticated"
    with main.db() as conn:
        attempts = conn.execute(
            "SELECT COUNT(*) AS c FROM auth_login_attempts WHERE provider = 'max' AND identifier = 'mx-retry' AND success = 1"
        ).fetchone()["c"]
    assert attempts == 1
