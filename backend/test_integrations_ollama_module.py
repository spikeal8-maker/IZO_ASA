"""Characterization tests for the isolated Ollama discovery boundary."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

import main
from app.integrations.ollama import (
    fetch_ollama_models_status,
    ollama_base_url,
    request_ollama_chat_message,
)


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


def test_chat_message_posts_unchanged_body_and_returns_content():
    body = {"model": "gemma4:12b", "stream": False, "messages": [{"role": "user", "content": "test"}]}
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"message": {"content": '{"improved_prompt":"готово"}'}, "done": True})

    content, payload = asyncio.run(
        request_ollama_chat_message(
            body=body,
            timeout_seconds=17,
            base_url="http://ollama.test:11434/",
            transport=httpx.MockTransport(handler),
        )
    )

    assert content == '{"improved_prompt":"готово"}'
    assert payload == {"message": {"content": '{"improved_prompt":"готово"}'}, "done": True}
    assert len(seen) == 1
    assert seen[0].method == "POST"
    assert seen[0].url.path == "/api/chat"
    assert seen[0].read() == httpx.Request("POST", "http://example.test", json=body).read()


def test_chat_message_preserves_empty_content_for_application_parser():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"other": "value"}})

    content, payload = asyncio.run(
        request_ollama_chat_message(
            body={},
            timeout_seconds=3,
            transport=httpx.MockTransport(handler),
        )
    )

    assert content == ""
    assert payload == {"message": {"other": "value"}}


def test_chat_message_preserves_legacy_http_error():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "busy", "secret": "not exposed"})

    with pytest.raises(RuntimeError, match=r"^Ollama вернула ошибку 429\.$"):
        asyncio.run(
            request_ollama_chat_message(
                body={},
                timeout_seconds=3,
                transport=httpx.MockTransport(handler),
            )
        )


def test_chat_message_preserves_invalid_json_error():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    with pytest.raises(json.JSONDecodeError):
        asyncio.run(
            request_ollama_chat_message(
                body={},
                timeout_seconds=3,
                transport=httpx.MockTransport(handler),
            )
        )


def test_prompt_improvement_keeps_body_timeout_and_application_parser(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_chat(*, body, timeout_seconds):
        captured.update({"body": body, "timeout": timeout_seconds})
        return '{"improved_prompt":"улучшенный результат"}', {"done": True}

    monkeypatch.setattr(main, "request_ollama_chat_message", fake_chat)
    request = main.ImprovePromptRequest(
        prompt="  исходный запрос  ",
        technicalPrompt="  технический контекст  ",
        mode="text",
        language="ru",
    )
    config = {
        **main.DEFAULT_ASSISTANT_MODELS_CONFIG["improve"],
        "localModel": "gemma4:12b",
        "localTimeoutSeconds": 999,
    }

    improved, payload = asyncio.run(main.improve_prompt_ollama(request, config))

    assert improved == "улучшенный результат"
    assert payload == {"done": True}
    assert captured["timeout"] == 120
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "gemma4:12b"
    assert body["stream"] is False
    assert body["think"] is False
    assert body["keep_alive"] == "5m"
    assert body["options"] == {"temperature": 0.25, "num_predict": 500}
    assert body["format"]["required"] == ["improved_prompt"]
    assert body["messages"][0]["role"] == "system"
    assert "Ответ верни на русском" in body["messages"][0]["content"]
    assert body["messages"][1] == {
        "role": "user",
        "content": '{"prompt": "исходный запрос", "technical_context": "технический контекст"}',
    }
