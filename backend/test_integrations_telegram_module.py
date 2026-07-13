"""Characterization tests for the Telegram Bot API transport boundary."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import HTTPException

import main
from app.integrations.telegram import (
    TelegramApiError,
    TelegramConfigurationError,
    TelegramResponseError,
    TelegramTransportError,
    probe_telegram_bot,
    request_telegram_bot_api,
    telegram_file_url,
)


def test_main_telegram_api_compatibility_wrapper_delegates(monkeypatch) -> None:
    calls: list[dict] = []
    expected = {"ok": True, "result": {"id": 42, "username": "izo_bot"}}

    async def fake_request(**kwargs):
        calls.append(kwargs)
        return expected

    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "telegram_test_token")
    monkeypatch.setattr(main, "request_telegram_bot_api", fake_request)

    assert asyncio.run(main.telegram_api("getMe")) == expected
    assert calls == [
        {
            "token": "telegram_test_token",
            "method": "getMe",
            "payload": None,
        }
    ]


def test_main_telegram_api_preserves_missing_token_error(monkeypatch) -> None:
    async def fake_request(**kwargs):
        raise TelegramConfigurationError("safe", method=kwargs["method"])

    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(main, "request_telegram_bot_api", fake_request)

    with pytest.raises(HTTPException) as captured:
        asyncio.run(main.telegram_api("getMe"))

    assert captured.value.status_code == 400
    assert captured.value.detail == "TELEGRAM_BOT_TOKEN is required for real Telegram API calls."


def test_main_telegram_api_preserves_api_error(monkeypatch) -> None:
    payload = {"ok": False, "error_code": 429, "description": "Too Many Requests"}

    async def fake_request(**kwargs):
        raise TelegramApiError(method=kwargs["method"], payload=payload)

    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "telegram_test_token")
    monkeypatch.setattr(main, "request_telegram_bot_api", fake_request)

    with pytest.raises(HTTPException) as captured:
        asyncio.run(main.telegram_api("sendMessage", {"chat_id": 7, "text": "hello"}))

    assert captured.value.status_code == 502
    assert captured.value.detail == (
        "Telegram API error: "
        "{'ok': False, 'error_code': 429, 'description': 'Too Many Requests'}"
    )


def test_request_posts_legacy_body_and_returns_envelope() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    result = asyncio.run(
        request_telegram_bot_api(
            token="telegram_test_token",
            method="sendMessage",
            payload={"chat_id": 7, "text": "hello"},
            timeout_seconds=17,
            transport=httpx.MockTransport(handler),
        )
    )

    assert result == {"ok": True, "result": {"message_id": 1}}
    assert len(seen) == 1
    assert seen[0].method == "POST"
    assert seen[0].url.path == "/bottelegram_test_token/sendMessage"
    assert seen[0].read() == httpx.Request(
        "POST",
        "http://example.test",
        json={"chat_id": 7, "text": "hello"},
    ).read()


def test_request_requires_token_without_network() -> None:
    with pytest.raises(TelegramConfigurationError, match="token is not configured"):
        asyncio.run(request_telegram_bot_api(token="", method="getMe"))


def test_request_exposes_typed_api_error_and_retry_after() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests",
                "parameters": {"retry_after": 8},
            },
        )

    with pytest.raises(TelegramApiError) as captured:
        asyncio.run(
            request_telegram_bot_api(
                token="telegram_test_token",
                method="getUpdates",
                transport=httpx.MockTransport(handler),
            )
        )

    assert captured.value.status_code == 429
    assert captured.value.retry_after == 8.0
    assert captured.value.payload["description"] == "Too Many Requests"
    assert "telegram_test_token" not in str(captured.value)


def test_request_exposes_sanitized_typed_http_error() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, headers={"Retry-After": "3"}, json={"ok": False})

    with pytest.raises(TelegramTransportError) as captured:
        asyncio.run(
            request_telegram_bot_api(
                token="telegram_test_token",
                method="getMe",
                transport=httpx.MockTransport(handler),
            )
        )

    assert captured.value.status_code == 401
    assert captured.value.retry_after == 3.0
    assert str(captured.value) == "Telegram Bot API returned HTTP 401 for getMe."
    assert "telegram_test_token" not in str(captured.value)


def test_request_hides_transport_details_and_token() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret transport detail", request=request)

    with pytest.raises(TelegramTransportError) as captured:
        asyncio.run(
            request_telegram_bot_api(
                token="telegram_test_token",
                method="getMe",
                transport=httpx.MockTransport(handler),
            )
        )

    assert str(captured.value) == "Telegram Bot API transport failed for getMe."
    assert "telegram_test_token" not in str(captured.value)
    assert "secret transport detail" not in str(captured.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"result": {}}),
        httpx.Response(200, json={"ok": "yes", "result": {}}),
    ],
)
def test_request_rejects_invalid_envelopes(response: httpx.Response) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return response

    with pytest.raises(TelegramResponseError):
        asyncio.run(
            request_telegram_bot_api(
                token="telegram_test_token",
                method="getMe",
                transport=httpx.MockTransport(handler),
            )
        )


def test_probe_reports_sanitized_success_and_configuration_state() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/getMe")
        return httpx.Response(
            200,
            json={"ok": True, "result": {"id": 42, "username": "izo_bot", "first_name": "IZO"}},
        )

    missing = asyncio.run(probe_telegram_bot(token=""))
    healthy = asyncio.run(
        probe_telegram_bot(
            token="telegram_test_token",
            transport=httpx.MockTransport(handler),
        )
    )

    assert missing.as_dict() == {
        "configured": False,
        "ok": False,
        "status": "not_configured",
        "bot_id": None,
        "username": None,
        "status_code": None,
        "error_type": None,
    }
    assert healthy.as_dict() == {
        "configured": True,
        "ok": True,
        "status": "ok",
        "bot_id": 42,
        "username": "izo_bot",
        "status_code": 200,
        "error_type": None,
    }


@pytest.mark.parametrize(
    ("response", "status", "error_type"),
    [
        (httpx.Response(401, json={"ok": False}), "unauthorized", "TelegramTransportError"),
        (
            httpx.Response(200, json={"ok": False, "error_code": 403, "description": "Forbidden"}),
            "unauthorized",
            "TelegramApiError",
        ),
        (httpx.Response(200, json={"ok": True, "result": {}}), "invalid_response", "TelegramResponseError"),
    ],
)
def test_probe_maps_failures_without_provider_details(
    response: httpx.Response,
    status: str,
    error_type: str,
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return response

    health = asyncio.run(
        probe_telegram_bot(
            token="telegram_test_token",
            transport=httpx.MockTransport(handler),
        )
    )

    assert health.ok is False
    assert health.status == status
    assert health.error_type == error_type
    assert "telegram_test_token" not in str(health.as_dict())


def test_file_url_preserves_official_shape_and_requires_token() -> None:
    assert telegram_file_url("telegram_test_token", "photos/avatar.jpg") == (
        "https://api.telegram.org/file/bottelegram_test_token/photos/avatar.jpg"
    )
    with pytest.raises(TelegramConfigurationError):
        telegram_file_url("", "photos/avatar.jpg")


def test_polling_error_helpers_accept_typed_telegram_errors() -> None:
    auth_error = TelegramTransportError("safe", method="getMe", status_code=401)
    retry_error = TelegramTransportError("safe", method="getUpdates", status_code=429, retry_after=9)

    assert main.is_auth_polling_error(auth_error) is True
    assert main.polling_retry_after(retry_error) == 9.0
