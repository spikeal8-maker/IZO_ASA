from __future__ import annotations

import asyncio
import ssl

import pytest

import main
from app.integrations.max_tls import build_max_http_verify, normalize_max_tls_trust_store


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "system"),
        ("", "system"),
        (" system ", "system"),
        ("CERTIFI", "certifi"),
    ],
)
def test_trust_store_mode_normalization(value, expected):
    assert normalize_max_tls_trust_store(value) == expected


def test_invalid_trust_store_mode_fails_fast():
    with pytest.raises(RuntimeError, match="MAX_TLS_TRUST_STORE"):
        normalize_max_tls_trust_store("disabled")


def test_system_mode_builds_native_context_with_tls_client_protocol():
    calls: list[object] = []
    sentinel = object()

    def factory(protocol):
        calls.append(protocol)
        return sentinel

    assert build_max_http_verify("system", system_context_factory=factory) is sentinel
    assert calls == [ssl.PROTOCOL_TLS_CLIENT]


def test_certifi_mode_preserves_httpx_default_verification():
    assert build_max_http_verify("certifi", system_context_factory=lambda _protocol: None) is True


def test_max_api_passes_configured_verify_context_without_exposing_token(monkeypatch):
    captured: dict[str, object] = {}
    verify_sentinel = object()

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"ok": True}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, method, url, headers, json=None, params=None):
            captured.update(method=method, url=url, headers=headers, json=json, params=params)
            return FakeResponse()

    monkeypatch.setattr(main, "MAX_BOT_TOKEN", "private-test-token")
    monkeypatch.setattr(main, "MAX_API_BASE_URL", "https://platform-api2.max.ru")
    monkeypatch.setattr(main, "MAX_HTTP_VERIFY", verify_sentinel)
    monkeypatch.setattr(main.httpx, "AsyncClient", FakeAsyncClient)

    assert asyncio.run(main.max_api("GET", "/me")) == {"ok": True}
    assert captured["client_kwargs"] == {"timeout": 30, "verify": verify_sentinel}
    assert captured["method"] == "GET"
    assert captured["url"] == "https://platform-api2.max.ru/me"
    assert captured["headers"] == {
        "Authorization": "private-test-token",
        "Content-Type": "application/json",
    }
