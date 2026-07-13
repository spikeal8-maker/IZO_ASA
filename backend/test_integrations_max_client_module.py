"""Contracts for the isolated MAX Bot API client."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import HTTPException

import main
from app.integrations.max_client import (
    MaxConfigurationError,
    MaxResponseError,
    MaxTransportError,
    probe_max_bot,
    request_max_api,
    request_max_bot_me,
)


def test_main_max_api_compatibility_wrapper_delegates(monkeypatch) -> None:
    calls: list[dict] = []
    expected = {"message": {"id": "message-1"}}

    async def fake_request(**kwargs):
        calls.append(kwargs)
        return expected

    verify = object()
    monkeypatch.setattr(main, "MAX_BOT_TOKEN", "max_test_token")
    monkeypatch.setattr(main, "MAX_API_BASE_URL", "https://max.test/")
    monkeypatch.setattr(main, "MAX_HTTP_VERIFY", verify)
    monkeypatch.setattr(main, "request_max_api", fake_request)

    assert asyncio.run(main.max_api("POST", "/messages", {"text": "hello"}, {"user_id": "7"})) == expected
    assert calls == [{
        "token": "max_test_token",
        "base_url": "https://max.test/",
        "verify": verify,
        "method": "POST",
        "path": "/messages",
        "payload": {"text": "hello"},
        "params": {"user_id": "7"},
    }]


def test_main_max_api_preserves_missing_token_error(monkeypatch) -> None:
    monkeypatch.setattr(main, "MAX_BOT_TOKEN", "")

    with pytest.raises(HTTPException) as captured:
        asyncio.run(main.max_api("GET", "/me"))

    assert captured.value.status_code == 400
    assert captured.value.detail == "MAX_BOT_TOKEN is required for real MAX API calls."


def test_async_request_preserves_headers_body_params_and_path() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"message": {"id": "message-1"}})

    result = asyncio.run(request_max_api(
        token="max_test_token",
        base_url="https://max.test/",
        verify=True,
        method="POST",
        path="/messages",
        payload={"text": "hello"},
        params={"user_id": "7"},
        timeout_seconds=17,
        transport=httpx.MockTransport(handler),
    ))
    assert result == {"message": {"id": "message-1"}}
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert request.url.path == "/messages"
    assert dict(request.url.params) == {"user_id": "7"}
    assert request.headers["Authorization"] == "max_test_token"
    assert request.headers["Content-Type"] == "application/json"
    assert request.read() == httpx.Request(
        "POST",
        "https://example.test",
        json={"text": "hello"},
    ).read()


@pytest.mark.parametrize(
    ("token", "base_url", "message"),
    [
        ("", "https://max.test", "token is not configured"),
        ("max_test_token", "", "base URL is not configured"),
        ("max_test_token", "///", "base URL is not configured"),
    ],
)
def test_async_request_rejects_missing_configuration(token: str, base_url: str, message: str) -> None:
    with pytest.raises(MaxConfigurationError, match=message):
        asyncio.run(request_max_api(
            token=token,
            base_url=base_url,
            verify=True,
            method="GET",
            path="/me",
        ))


def test_async_request_exposes_typed_http_error_and_retry_after() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"details": {"retry_after": 8}})

    with pytest.raises(MaxTransportError) as captured:
        asyncio.run(request_max_api(
            token="max_test_token",
            base_url="https://max.test",
            verify=True,
            method="GET",
            path="/updates",
            transport=httpx.MockTransport(handler),
        ))

    assert captured.value.operation == "GET /updates"
    assert captured.value.status_code == 429
    assert captured.value.retry_after == 8.0
    assert str(captured.value) == "MAX API returned HTTP 429."
    assert "max_test_token" not in str(captured.value)


def test_async_request_hides_transport_details_and_token() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private network detail", request=request)

    with pytest.raises(MaxTransportError) as captured:
        asyncio.run(request_max_api(
            token="max_test_token",
            base_url="https://max.test",
            verify=True,
            method="GET",
            path="/me",
            transport=httpx.MockTransport(handler),
        ))

    assert str(captured.value) == "MAX API transport failed."
    assert "private network detail" not in str(captured.value)
    assert "max_test_token" not in str(captured.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json=[]),
        httpx.Response(204),
    ],
)
def test_async_request_rejects_invalid_payload(response: httpx.Response) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return response

    with pytest.raises(MaxResponseError):
        asyncio.run(request_max_api(
            token="max_test_token",
            base_url="https://max.test",
            verify=True,
            method="GET",
            path="/me",
            transport=httpx.MockTransport(handler),
        ))


def test_sync_me_preserves_startup_contract() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"username": "izo_max_bot"})

    payload, status_code = request_max_bot_me(
        token="max_test_token",
        base_url="https://max.test/",
        verify=True,
        transport=httpx.MockTransport(handler),
    )

    assert payload == {"username": "izo_max_bot"}
    assert status_code == 200
    assert len(seen) == 1
    assert seen[0].method == "GET"
    assert seen[0].url.path == "/me"
    assert seen[0].headers["Authorization"] == "max_test_token"
    assert seen[0].headers["Content-Type"] == "application/json"


def test_sync_me_exposes_sanitized_typed_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "token max_test_token is invalid"})

    with pytest.raises(MaxTransportError) as captured:
        request_max_bot_me(
            token="max_test_token",
            base_url="https://max.test",
            verify=True,
            transport=httpx.MockTransport(handler),
        )

    assert captured.value.status_code == 403
    assert str(captured.value) == "MAX API returned HTTP 403."
    assert "max_test_token" not in str(captured.value)


def test_main_deep_link_cache_preserves_typed_http_status(monkeypatch, capsys) -> None:
    def fake_me(**_kwargs):
        raise MaxTransportError("safe", operation="GET /me", status_code=403)

    monkeypatch.setattr(main, "MAX_BOT_DEEP_LINK_BASE", "")
    monkeypatch.setattr(main, "MAX_BOT_TOKEN", "max_test_token")
    monkeypatch.setattr(main, "request_max_bot_me", fake_me)
    main._MAX_BOT_DEEP_LINK_CACHE.update({
        "attempted": False,
        "base": None,
        "source": None,
        "resolved": False,
        "api_status": None,
        "fields": [],
    })

    assert main.resolve_max_bot_deep_link_base() is None
    assert main._MAX_BOT_DEEP_LINK_CACHE["api_status"] == 403
    output = capsys.readouterr().out
    assert "status=403" in output
    assert "max_test_token" not in output


def test_health_reports_sanitized_success_and_configuration_state() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "bot-1", "username": "izo_max_bot", "private": "hidden"})

    missing = asyncio.run(probe_max_bot(token="", base_url="https://max.test", verify=True))
    healthy = asyncio.run(probe_max_bot(
        token="max_test_token",
        base_url="https://max.test",
        verify=True,
        transport=httpx.MockTransport(handler),
    ))

    assert missing.as_dict() == {
        "configured": False,
        "ok": False,
        "status": "not_configured",
        "status_code": None,
        "error_type": None,
    }
    assert healthy.as_dict() == {
        "configured": True,
        "ok": True,
        "status": "ok",
        "status_code": 200,
        "error_type": None,
    }
    assert "private" not in str(healthy.as_dict())
    assert "izo_max_bot" not in str(healthy.as_dict())


@pytest.mark.parametrize(
    ("response", "status", "error_type"),
    [
        (httpx.Response(401, json={"message": "unauthorized"}), "unauthorized", "MaxTransportError"),
        (httpx.Response(503, json={"message": "unavailable"}), "unavailable", "MaxTransportError"),
        (httpx.Response(200, content=b"not-json"), "invalid_response", "MaxResponseError"),
    ],
)
def test_health_maps_failures_without_provider_payload(
    response: httpx.Response,
    status: str,
    error_type: str,
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return response

    health = asyncio.run(probe_max_bot(
        token="max_test_token",
        base_url="https://max.test",
        verify=True,
        transport=httpx.MockTransport(handler),
    ))

    assert health.ok is False
    assert health.status == status
    assert health.error_type == error_type
    assert "max_test_token" not in str(health.as_dict())


def test_polling_helpers_accept_typed_max_errors() -> None:
    auth_error = MaxTransportError("safe", operation="GET /me", status_code=401)
    retry_error = MaxTransportError("safe", operation="GET /updates", status_code=429, retry_after=6)

    assert main.is_auth_polling_error(auth_error) is True
    assert main.polling_retry_after(retry_error) == 6.0
