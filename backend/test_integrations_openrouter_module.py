"""Characterization tests for the isolated OpenRouter text-model catalog."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

import main
from app.integrations.openrouter import (
    fetch_openrouter_key_details,
    fetch_openrouter_text_models,
    parse_openrouter_text_models,
)


TEXT_ARCHITECTURE = {"input_modalities": ["text"], "output_modalities": ["text"]}


def test_text_model_parser_filters_modalities_prices_and_sorts():
    payload = {
        "data": [
            {
                "id": "z/model",
                "name": "beta",
                "architecture": TEXT_ARCHITECTURE,
                "pricing": {"prompt": "0.000000077", "completion": "0.000000154"},
                "context_length": 1_048_576,
            },
            {
                "id": "a/model",
                "name": "Alpha",
                "architecture": TEXT_ARCHITECTURE,
                "pricing": {"prompt": 0.000001, "completion": 0.000002},
                "context_length": "4096",
            },
            {
                "id": "image-only",
                "architecture": {"input_modalities": ["text"], "output_modalities": ["image"]},
            },
            {"id": "missing-architecture"},
            {"name": "missing id", "architecture": TEXT_ARCHITECTURE},
            "not-a-row",
        ]
    }

    assert parse_openrouter_text_models(payload) == [
        {
            "id": "a/model",
            "name": "Alpha",
            "inputPerMillionUsd": 1.0,
            "outputPerMillionUsd": 2.0,
            "contextLength": 4096,
        },
        {
            "id": "z/model",
            "name": "beta",
            "inputPerMillionUsd": 0.077,
            "outputPerMillionUsd": 0.154,
            "contextLength": 1_048_576,
        },
    ]


def test_text_model_parser_preserves_invalid_pricing_fallback_and_default_name():
    models = parse_openrouter_text_models({
        "data": [{
            "id": "fallback/model",
            "architecture": TEXT_ARCHITECTURE,
            "pricing": {"prompt": "invalid", "completion": "0.5"},
        }]
    })

    assert models == [{
        "id": "fallback/model",
        "name": "fallback/model",
        "inputPerMillionUsd": 0,
        "outputPerMillionUsd": 0,
        "contextLength": 0,
    }]
    assert parse_openrouter_text_models(None) == []
    assert parse_openrouter_text_models({"data": {}}) == []


def test_text_model_fetch_preserves_path_headers_and_parsing():
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": [{
            "id": "deepseek/deepseek-v4-flash",
            "name": "DeepSeek V4 Flash",
            "architecture": TEXT_ARCHITECTURE,
            "pricing": {"prompt": "0.000000077", "completion": "0.000000154"},
            "context_length": 1_048_576,
        }]})

    result = asyncio.run(fetch_openrouter_text_models(
        base_url="https://openrouter.test/api/v1/",
        headers={"Authorization": "Bearer test-token", "X-Title": "IZO ASA"},
        timeout_seconds=15,
        transport=httpx.MockTransport(handler),
    ))

    assert result[0]["id"] == "deepseek/deepseek-v4-flash"
    assert len(seen) == 1
    assert seen[0].method == "GET"
    assert seen[0].url.path == "/api/v1/models"
    assert dict(seen[0].url.params) == {"output_modalities": "text"}
    assert seen[0].headers["Authorization"] == "Bearer test-token"
    assert seen[0].headers["X-Title"] == "IZO ASA"


def test_text_model_fetch_returns_empty_for_empty_body():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"")

    assert asyncio.run(fetch_openrouter_text_models(
        base_url="https://openrouter.test/api/v1",
        headers={},
        transport=httpx.MockTransport(handler),
    )) == []


def test_text_model_fetch_preserves_http_and_json_errors():
    async def http_error(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(fetch_openrouter_text_models(
            base_url="https://openrouter.test/api/v1",
            headers={},
            transport=httpx.MockTransport(http_error),
        ))

    async def invalid_json(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    with pytest.raises(json.JSONDecodeError):
        asyncio.run(fetch_openrouter_text_models(
            base_url="https://openrouter.test/api/v1",
            headers={},
            transport=httpx.MockTransport(invalid_json),
        ))


def test_main_text_model_wrapper_preserves_header_policy_and_cache_update(monkeypatch):
    captured: dict[str, object] = {}
    expected = [{"id": "cached/model", "name": "Cached"}]

    async def fake_fetch(**kwargs):
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(main, "fetch_openrouter_text_models", fake_fetch)
    monkeypatch.setattr(main, "openrouter_api_key", lambda: "")
    monkeypatch.setattr(main.time, "monotonic", lambda: 500.0)
    monkeypatch.setattr(main, "_openrouter_text_model_cache", {"ts": 0.0, "models": []})

    assert asyncio.run(main.openrouter_text_models(force=True)) == expected
    assert captured == {
        "base_url": main.OPENROUTER_BASE_URL,
        "headers": {"Content-Type": "application/json"},
        "timeout_seconds": 15,
    }
    assert main._openrouter_text_model_cache == {"ts": 500.0, "models": expected}


def test_main_text_model_wrapper_uses_fresh_cache_without_http(monkeypatch):
    expected = [{"id": "cached/model", "name": "Cached"}]

    async def unexpected_fetch(**_kwargs):
        raise AssertionError("fresh cache must avoid OpenRouter HTTP")

    monkeypatch.setattr(main, "fetch_openrouter_text_models", unexpected_fetch)
    monkeypatch.setattr(main.time, "monotonic", lambda: 1_000.0)
    monkeypatch.setattr(main, "_openrouter_text_model_cache", {"ts": 999.0, "models": expected})

    assert asyncio.run(main.openrouter_text_models()) == expected


def test_key_details_preserve_paths_headers_data_and_balance():
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/key"):
            return httpx.Response(200, json={"data": {"limit": 10, "usage": 2}})
        return httpx.Response(200, json={"data": {"total_credits": 10.125, "total_usage": 2.1}})

    result = asyncio.run(fetch_openrouter_key_details(
        base_url="https://openrouter.test/api/v1/",
        key_headers={"Authorization": "Bearer key-request"},
        credits_headers={"Authorization": "Bearer credits-request"},
        timeout_seconds=15,
        transport=httpx.MockTransport(handler),
    ))

    assert result == {
        "ok": True,
        "status_code": 200,
        "data": {"limit": 10, "usage": 2},
        "credits": {
            "ok": True,
            "status_code": 200,
            "data": {"total_credits": 10.125, "total_usage": 2.1},
            "balance": 8.025,
        },
    }
    assert [request.url.path for request in seen] == ["/api/v1/key", "/api/v1/credits"]
    assert seen[0].headers["Authorization"] == "Bearer key-request"
    assert seen[1].headers["Authorization"] == "Bearer credits-request"


def test_key_details_preserve_key_error_after_both_requests():
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/key"):
            return httpx.Response(401, json={"error": {"message": "invalid key"}})
        return httpx.Response(200, json={"data": {"total_credits": 100, "total_usage": 1}})

    result = asyncio.run(fetch_openrouter_key_details(
        base_url="https://openrouter.test/api/v1",
        key_headers={},
        credits_headers={},
        transport=httpx.MockTransport(handler),
    ))

    assert seen == ["/api/v1/key", "/api/v1/credits"]
    assert result == {
        "ok": False,
        "status_code": 401,
        "error": {"message": "invalid key"},
    }


def test_key_details_preserve_nested_credits_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/key"):
            return httpx.Response(200, json={"data": {"limit": 10}})
        return httpx.Response(503, json={"error": "credits unavailable"})

    result = asyncio.run(fetch_openrouter_key_details(
        base_url="https://openrouter.test/api/v1",
        key_headers={},
        credits_headers={},
        transport=httpx.MockTransport(handler),
    ))

    assert result["ok"] is True
    assert result["credits"] == {
        "ok": False,
        "status_code": 503,
        "error": "credits unavailable",
    }


def test_key_details_preserve_invalid_json_exception():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/key"):
            return httpx.Response(200, content=b"not-json")
        return httpx.Response(200, json={})

    with pytest.raises(json.JSONDecodeError):
        asyncio.run(fetch_openrouter_key_details(
            base_url="https://openrouter.test/api/v1",
            key_headers={},
            credits_headers={},
            transport=httpx.MockTransport(handler),
        ))


def test_main_key_status_without_key_skips_integration(monkeypatch):
    async def unexpected_fetch(**_kwargs):
        raise AssertionError("OpenRouter HTTP must not run without a key")

    monkeypatch.setattr(main, "openrouter_api_key", lambda: "")
    monkeypatch.setattr(main, "fetch_openrouter_key_details", unexpected_fetch)

    assert asyncio.run(main.fetch_openrouter_key_status()) == {
        "configured": False,
        "ok": False,
        "error": "OPENROUTER_API_KEY не задан",
    }


def test_main_key_status_preserves_header_calls_source_and_shape(monkeypatch):
    captured: dict[str, object] = {}
    header_calls = 0

    def fake_headers():
        nonlocal header_calls
        header_calls += 1
        return {"X-Request": str(header_calls)}

    async def fake_fetch(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "status_code": 200, "data": {"limit": 10}, "credits": {"ok": True}}

    monkeypatch.setattr(main, "openrouter_api_key", lambda: "configured-secret")
    monkeypatch.setattr(main, "openrouter_api_key_source", lambda: "admin_ui")
    monkeypatch.setattr(main, "openrouter_headers", fake_headers)
    monkeypatch.setattr(main, "fetch_openrouter_key_details", fake_fetch)

    result = asyncio.run(main.fetch_openrouter_key_status())

    assert result == {
        "configured": True,
        "source": "admin_ui",
        "ok": True,
        "status_code": 200,
        "data": {"limit": 10},
        "credits": {"ok": True},
    }
    assert captured == {
        "base_url": main.OPENROUTER_BASE_URL,
        "key_headers": {"X-Request": "1"},
        "credits_headers": {"X-Request": "2"},
        "timeout_seconds": 15,
    }


def test_main_key_status_preserves_safe_exception_wrapper(monkeypatch):
    async def failed_fetch(**_kwargs):
        raise httpx.ConnectError("provider unavailable")

    monkeypatch.setattr(main, "openrouter_api_key", lambda: "configured-secret")
    monkeypatch.setattr(main, "openrouter_api_key_source", lambda: "env")
    monkeypatch.setattr(main, "openrouter_headers", lambda: {"Authorization": "not-returned"})
    monkeypatch.setattr(main, "fetch_openrouter_key_details", failed_fetch)

    assert asyncio.run(main.fetch_openrouter_key_status()) == {
        "configured": True,
        "source": "env",
        "ok": False,
        "error": "provider unavailable",
    }
