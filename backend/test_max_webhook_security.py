from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from test_support.browser_client import BrowserTestClient

import main
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
    monkeypatch.setattr(main, "MAX_WEBHOOK_MAX_BODY_BYTES", 256)
    main.MAX_POLLING_DIAG["lastWebhookAt"] = None
    main.MAX_POLLING_DIAG["lastWebhookError"] = None


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
    client = BrowserTestClient(main.app)

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
    client = BrowserTestClient(main.app)

    response = client.post(
        "/api/max/webhook",
        json={"message": {"body": {"text": "/app"}}},
        headers=headers,
    )

    assert response.status_code == 403
    assert calls == []


def test_max_webhook_rejects_runtime_misconfiguration(monkeypatch):
    monkeypatch.setattr(main, "MAX_WEBHOOK_SECRET", "")
    client = BrowserTestClient(main.app)

    response = client.post("/api/max/webhook", json={"message": {}})

    assert response.status_code == 503


def test_max_webhook_enforces_body_limit_and_json_object(monkeypatch):
    calls: list[dict] = []

    async def fake_handler(payload, send_replies):
        calls.append(payload)

    monkeypatch.setattr(main, "handle_max_update", fake_handler)
    client = BrowserTestClient(main.app)
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
    client = BrowserTestClient(main.app)
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
    assert main.MAX_POLLING_DIAG["lastWebhookAt"] is not None
