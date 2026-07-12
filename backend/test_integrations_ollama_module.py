"""Characterization tests for the isolated Ollama discovery boundary."""

from __future__ import annotations

import asyncio

import httpx
import pytest

import main
from app.integrations.ollama import fetch_ollama_models_status, ollama_base_url


def test_ollama_base_url_uses_environment_and_removes_trailing_slashes(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.internal:11434///")
    assert ollama_base_url() == "http://ollama.internal:11434"
    assert ollama_base_url("http://127.0.0.1:11434/") == "http://127.0.0.1:11434"


def test_main_compatibility_wrapper_delegates_to_integration(monkeypatch):
    expected = {"ok": True, "baseUrl": "http://ollama.test:11434", "models": []}

    async def fake_status():
        return expected

    monkeypatch.setattr(main, "fetch_ollama_models_status", fake_status)
    assert asyncio.run(main.ollama_models_status()) == expected


def test_models_status_preserves_ollama_model_rows_and_request_path():
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={"models": [{"name": "gemma4:31b-cloud", "size": 42}]},
        )

    result = asyncio.run(
        fetch_ollama_models_status(
            base_url="http://ollama.test:11434/",
            transport=httpx.MockTransport(handler),
        )
    )

    assert result == {
        "ok": True,
        "baseUrl": "http://ollama.test:11434",
        "models": [{"name": "gemma4:31b-cloud", "size": 42}],
    }
    assert [request.url.path for request in seen] == ["/api/tags"]


@pytest.mark.parametrize(
    ("response", "expected_error"),
    [
        (httpx.Response(200, json={"models": {"name": "not-a-list"}}), None),
        (httpx.Response(503, json={"error": "unavailable"}), "HTTPStatusError"),
        (httpx.Response(200, content=b"not-json"), "JSONDecodeError"),
    ],
)
def test_models_status_preserves_safe_fallbacks(response: httpx.Response, expected_error: str | None):
    async def handler(_request: httpx.Request) -> httpx.Response:
        return response

    result = asyncio.run(
        fetch_ollama_models_status(
            base_url="http://ollama.test:11434",
            transport=httpx.MockTransport(handler),
        )
    )

    if expected_error is None:
        assert result == {"ok": True, "baseUrl": "http://ollama.test:11434", "models": []}
    else:
        assert result == {
            "ok": False,
            "baseUrl": "http://ollama.test:11434",
            "models": [],
            "error": expected_error,
        }


def test_models_status_hides_connection_error_details():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret internal detail", request=request)

    result = asyncio.run(
        fetch_ollama_models_status(
            base_url="http://ollama.test:11434",
            transport=httpx.MockTransport(handler),
        )
    )

    assert result == {
        "ok": False,
        "baseUrl": "http://ollama.test:11434",
        "models": [],
        "error": "ConnectError",
    }
