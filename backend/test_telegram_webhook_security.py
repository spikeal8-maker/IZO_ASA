from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from test_support.browser_client import BrowserTestClient

import main
from app.security import webhooks
from app.security.webhooks import (
    WebhookReplayGuard,
    build_telegram_set_webhook_payload,
    validate_telegram_webhook_secret,
    webhook_secret_matches,
)


TEST_SECRET = "Unit_Test-Secret_123"
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


@pytest.fixture(autouse=True)
def isolated_webhook_state(monkeypatch):
    monkeypatch.setattr(main, "BOT_UPDATES_MODE", "webhook")
    monkeypatch.setattr(main, "BOT_MODE", "webhook")
    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(main, "TELEGRAM_WEBHOOK_SECRET", TEST_SECRET)
    monkeypatch.setattr(main, "TELEGRAM_WEBHOOK_MAX_BODY_BYTES", 256)
    main._telegram_webhook_replay_guard.clear()


def test_webhook_secret_is_required_only_in_webhook_mode():
    validate_telegram_webhook_secret("polling", "")
    validate_telegram_webhook_secret("disabled", "")

    with pytest.raises(RuntimeError, match="TELEGRAM_WEBHOOK_SECRET is required"):
        validate_telegram_webhook_secret("webhook", "")
    with pytest.raises(RuntimeError, match="letters, digits, underscore and hyphen"):
        validate_telegram_webhook_secret("webhook", "not valid with spaces")
    with pytest.raises(RuntimeError, match="at most 256"):
        validate_telegram_webhook_secret("webhook", "a" * 257)

    validate_telegram_webhook_secret("webhook", TEST_SECRET)


def test_secret_comparison_uses_constant_time_bytes(monkeypatch):
    seen: list[tuple[bytes, bytes]] = []

    def fake_compare(left: bytes, right: bytes) -> bool:
        seen.append((left, right))
        return left == right

    monkeypatch.setattr(webhooks.hmac, "compare_digest", fake_compare)

    assert webhook_secret_matches(TEST_SECRET, TEST_SECRET) is True
    assert webhook_secret_matches(TEST_SECRET, "wrong") is False
    assert webhook_secret_matches(TEST_SECRET, None) is False
    assert seen == [
        (TEST_SECRET.encode("ascii"), TEST_SECRET.encode("ascii")),
        (TEST_SECRET.encode("ascii"), b"wrong"),
    ]


def test_set_webhook_payload_includes_secret_token_without_logging_helpers():
    assert build_telegram_set_webhook_payload("https://example.test/", TEST_SECRET) == {
        "url": "https://example.test/api/telegram/webhook",
        "secret_token": TEST_SECRET,
    }


def test_replay_guard_is_bounded_and_ignores_missing_ids():
    guard = WebhookReplayGuard(max_entries=2)

    assert guard.claim(None) is True
    assert guard.claim(True) is True
    assert guard.claim(10) is True
    assert guard.claim(10) is False
    assert guard.claim(11) is True
    assert guard.claim(12) is True
    assert guard.claim(10) is True
    assert len(guard) == 2


def test_startup_rejects_missing_secret_before_database_preflight(monkeypatch):
    monkeypatch.setattr(main, "TELEGRAM_WEBHOOK_SECRET", "")
    database_preflight_called = False

    def unexpected_database_preflight():
        nonlocal database_preflight_called
        database_preflight_called = True

    monkeypatch.setattr(main, "db_guard_preflight", unexpected_database_preflight)

    with pytest.raises(RuntimeError, match="TELEGRAM_WEBHOOK_SECRET is required"):
        asyncio.run(main.startup())
    assert database_preflight_called is False


def test_polling_mode_disables_public_webhook_receiver(monkeypatch):
    monkeypatch.setattr(main, "BOT_UPDATES_MODE", "polling")
    client = BrowserTestClient(main.app)

    response = client.post(
        "/api/telegram/webhook",
        json={"update_id": 1},
        headers={SECRET_HEADER: TEST_SECRET},
    )

    assert response.status_code == 404


@pytest.mark.parametrize("header_value", [None, "wrong-secret"])
def test_webhook_rejects_missing_or_invalid_secret(header_value, monkeypatch):
    calls: list[dict] = []

    async def fake_handler(payload, send_replies):
        calls.append(payload)

    monkeypatch.setattr(main, "handle_telegram_update", fake_handler)
    headers = {SECRET_HEADER: header_value} if header_value is not None else {}
    client = BrowserTestClient(main.app)

    response = client.post("/api/telegram/webhook", json={"update_id": 2}, headers=headers)

    assert response.status_code == 403
    assert calls == []


def test_webhook_rejects_runtime_misconfiguration(monkeypatch):
    monkeypatch.setattr(main, "TELEGRAM_WEBHOOK_SECRET", "")
    client = BrowserTestClient(main.app)

    response = client.post("/api/telegram/webhook", json={"update_id": 3})

    assert response.status_code == 503


def test_webhook_enforces_actual_body_limit_before_json_handling(monkeypatch):
    calls: list[dict] = []

    async def fake_handler(payload, send_replies):
        calls.append(payload)

    monkeypatch.setattr(main, "handle_telegram_update", fake_handler)
    client = BrowserTestClient(main.app)

    response = client.post(
        "/api/telegram/webhook",
        content=b"{" + (b" " * 300) + b"}",
        headers={SECRET_HEADER: TEST_SECRET, "Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert calls == []


@pytest.mark.parametrize(
    "body",
    [b"not-json", b"[]", b'"string"'],
)
def test_webhook_rejects_invalid_or_non_object_json(body, monkeypatch):
    calls: list[dict] = []

    async def fake_handler(payload, send_replies):
        calls.append(payload)

    monkeypatch.setattr(main, "handle_telegram_update", fake_handler)
    client = BrowserTestClient(main.app)

    response = client.post(
        "/api/telegram/webhook",
        content=body,
        headers={SECRET_HEADER: TEST_SECRET, "Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert calls == []


def test_valid_update_is_handled_once_and_replay_is_acknowledged(monkeypatch):
    calls: list[tuple[dict, bool]] = []

    async def fake_handler(payload, send_replies):
        calls.append((payload, send_replies))

    monkeypatch.setattr(main, "handle_telegram_update", fake_handler)
    client = BrowserTestClient(main.app)
    payload = {"update_id": 777, "message": {"text": "/app", "chat": {"id": 42}}}
    headers = {SECRET_HEADER: TEST_SECRET}

    first = client.post("/api/telegram/webhook", json=payload, headers=headers)
    replay = client.post("/api/telegram/webhook", json=payload, headers=headers)

    assert first.status_code == 200
    assert first.json() == {"ok": True}
    assert replay.status_code == 200
    assert replay.json() == {"ok": True, "duplicate": True}
    assert calls == [(payload, True)]
