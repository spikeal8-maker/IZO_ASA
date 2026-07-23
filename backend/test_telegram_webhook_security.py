from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

import main
from app.api.routers import bots_public
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
    monkeypatch.setattr(bots_public, "TELEGRAM_WEBHOOK_MAX_BODY_BYTES", 256)
    bots_public._telegram_webhook_replay_guard.clear()


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
    guard.release(10)
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
    client = TestClient(main.app)

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
    client = TestClient(main.app)

    response = client.post("/api/telegram/webhook", json={"update_id": 2}, headers=headers)

    assert response.status_code == 403
    assert calls == []


def test_webhook_rejects_runtime_misconfiguration(monkeypatch):
    monkeypatch.setattr(main, "TELEGRAM_WEBHOOK_SECRET", "")
    client = TestClient(main.app)

    response = client.post("/api/telegram/webhook", json={"update_id": 3})

    assert response.status_code == 503


def test_webhook_enforces_actual_body_limit_before_json_handling(monkeypatch):
    calls: list[dict] = []

    async def fake_handler(payload, send_replies):
        calls.append(payload)

    monkeypatch.setattr(main, "handle_telegram_update", fake_handler)
    client = TestClient(main.app)

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
    client = TestClient(main.app)

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
    client = TestClient(main.app)
    payload = {"update_id": 777, "message": {"text": "/app", "chat": {"id": 42}}}
    headers = {SECRET_HEADER: TEST_SECRET}

    first = client.post("/api/telegram/webhook", json=payload, headers=headers)
    replay = client.post("/api/telegram/webhook", json=payload, headers=headers)

    assert first.status_code == 200
    assert first.json() == {"ok": True}
    assert replay.status_code == 200
    assert replay.json() == {"ok": True, "duplicate": True}
    assert calls == [(payload, True)]


def test_failed_update_is_released_for_provider_retry(monkeypatch):
    calls: list[dict] = []

    async def flaky_handler(payload, send_replies):
        calls.append(payload)
        if len(calls) == 1:
            raise RuntimeError("temporary provider failure")

    monkeypatch.setattr(main, "handle_telegram_update", flaky_handler)
    client = TestClient(main.app)
    payload = {"update_id": 778, "message": {"text": "/start", "chat": {"id": 42}}}
    headers = {SECRET_HEADER: TEST_SECRET}

    failed = client.post("/api/telegram/webhook", json=payload, headers=headers)
    retried = client.post("/api/telegram/webhook", json=payload, headers=headers)
    duplicate = client.post("/api/telegram/webhook", json=payload, headers=headers)

    assert failed.status_code == 503
    assert retried.status_code == 200
    assert duplicate.json() == {"ok": True, "duplicate": True}
    assert calls == [payload, payload]


def test_provider_retry_after_post_approval_send_failure_is_idempotent(tmp_path, monkeypatch):
    send_attempts = 0
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "telegram-retry.sqlite3")
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    monkeypatch.setattr(main, "APP_ENV", "development")
    monkeypatch.setattr(main, "TELEGRAM_BOT_USERNAME", "OneNodeTestBot")
    main.init_db()

    async def flaky_telegram_api(method, payload=None):
        nonlocal send_attempts
        if method == "sendMessage":
            send_attempts += 1
            if send_attempts == 1:
                raise RuntimeError("temporary send failure")
        return {"ok": True, "result": {}}

    monkeypatch.setattr(main, "telegram_api", flaky_telegram_api)
    client = TestClient(main.app)
    started = client.post("/api/auth/bot-login/start", json={"provider": "telegram"}).json()
    payload_value = parse_qs(urlparse(started["deep_link"]).query)["start"][0]
    update = {
        "update_id": 779,
        "callback_query": {
            "id": "retry-callback",
            "data": f"approve:{payload_value}",
            "from": {"id": 909, "username": "retry_user", "first_name": "Retry"},
            "message": {"chat": {"id": 909}},
        },
    }
    headers = {SECRET_HEADER: TEST_SECRET}
    provider_client = TestClient(main.app)

    assert provider_client.post("/api/telegram/webhook", json=update, headers=headers).status_code == 503
    assert provider_client.post("/api/telegram/webhook", json=update, headers=headers).status_code == 200
    assert send_attempts == 2
    assert client.get("/api/auth/bot-login/status").json()["status"] == "authenticated"
    with main.db() as conn:
        attempts = conn.execute(
            "SELECT COUNT(*) AS c FROM auth_login_attempts WHERE provider = 'telegram' AND identifier = '909' AND success = 1"
        ).fetchone()["c"]
    assert attempts == 1
