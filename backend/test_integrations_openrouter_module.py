"""Characterization tests for the isolated OpenRouter text-model catalog."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

import main
from app.integrations.openrouter import (
    fetch_openrouter_key_details,
    fetch_openrouter_image_model_documents,
    fetch_openrouter_text_models,
    parse_openrouter_text_models,
    request_openrouter_chat_completion,
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


def test_chat_completion_transport_preserves_path_headers_body_status_and_payload():
    body = {"model": "deepseek/test", "messages": [{"role": "user", "content": "test"}]}
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202, json={"id": "response-1", "choices": []})

    status_code, payload = asyncio.run(request_openrouter_chat_completion(
        base_url="https://openrouter.test/api/v1/",
        headers={"Authorization": "Bearer test", "X-Title": "IZO ASA"},
        body=body,
        timeout_seconds=17,
        transport=httpx.MockTransport(handler),
    ))

    assert status_code == 202
    assert payload == {"id": "response-1", "choices": []}
    assert len(seen) == 1
    assert seen[0].method == "POST"
    assert seen[0].url.path == "/api/v1/chat/completions"
    assert seen[0].headers["Authorization"] == "Bearer test"
    assert seen[0].headers["X-Title"] == "IZO ASA"
    assert seen[0].read() == httpx.Request("POST", "https://example.test", json=body).read()


def test_chat_completion_transport_preserves_empty_payload():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(204, content=b"")

    assert asyncio.run(request_openrouter_chat_completion(
        base_url="https://openrouter.test/api/v1",
        headers={},
        body={},
        timeout_seconds=3,
        transport=httpx.MockTransport(handler),
    )) == (204, {})


def test_chat_completion_transport_preserves_json_and_network_errors():
    async def invalid_json(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    with pytest.raises(json.JSONDecodeError):
        asyncio.run(request_openrouter_chat_completion(
            base_url="https://openrouter.test/api/v1",
            headers={},
            body={},
            timeout_seconds=3,
            transport=httpx.MockTransport(invalid_json),
        ))

    async def network_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unavailable", request=request)

    with pytest.raises(httpx.ConnectError, match="unavailable"):
        asyncio.run(request_openrouter_chat_completion(
            base_url="https://openrouter.test/api/v1",
            headers={},
            body={},
            timeout_seconds=3,
            transport=httpx.MockTransport(network_error),
        ))


def test_prompt_improvement_keeps_openrouter_body_timeout_and_parser(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_chat(**kwargs):
        captured.update(kwargs)
        return 200, {
            "choices": [{"message": {"content": '{"improved_prompt":"улучшенный API результат"}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4},
        }

    monkeypatch.setattr(main, "openrouter_api_key", lambda: "configured-secret")
    monkeypatch.setattr(main, "openrouter_headers", lambda: {"Authorization": "not-returned"})
    monkeypatch.setattr(main, "request_openrouter_chat_completion", fake_chat)
    request = main.ImprovePromptRequest(
        prompt="  исходный API запрос  ",
        technicalPrompt="  технический API контекст  ",
        mode="text",
        language="ru",
    )
    config = {
        **main.DEFAULT_ASSISTANT_MODELS_CONFIG["improve"],
        "apiModel": "deepseek/deepseek-v4-flash",
        "apiTimeoutSeconds": 999,
    }

    improved, payload = asyncio.run(main.improve_prompt_openrouter(request, config))

    assert improved == "улучшенный API результат"
    assert payload["usage"] == {"prompt_tokens": 10, "completion_tokens": 4}
    assert captured["base_url"] == main.OPENROUTER_BASE_URL
    assert captured["headers"] == {"Authorization": "not-returned"}
    assert captured["timeout_seconds"] == 30
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "deepseek/deepseek-v4-flash"
    assert body["temperature"] == 0.25
    assert body["max_tokens"] == 500
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
    assert "Ответ верни на русском" in body["messages"][0]["content"]
    assert body["messages"][1] == {
        "role": "user",
        "content": '{"prompt": "исходный API запрос", "technical_context": "технический API контекст"}',
    }


def test_prompt_improvement_without_key_skips_transport(monkeypatch):
    async def unexpected_chat(**_kwargs):
        raise AssertionError("OpenRouter HTTP must not run without a key")

    monkeypatch.setattr(main, "openrouter_api_key", lambda: "")
    monkeypatch.setattr(main, "request_openrouter_chat_completion", unexpected_chat)

    with pytest.raises(RuntimeError, match=r"^OpenRouter API-ключ не настроен\.$"):
        asyncio.run(main.improve_prompt_openrouter(main.ImprovePromptRequest(prompt="test")))


def test_prompt_improvement_preserves_public_provider_error(monkeypatch):
    async def failed_chat(**_kwargs):
        return 429, {"error": {"message": "rate limited"}}

    monkeypatch.setattr(main, "openrouter_api_key", lambda: "configured-secret")
    monkeypatch.setattr(main, "openrouter_headers", lambda: {})
    monkeypatch.setattr(main, "request_openrouter_chat_completion", failed_chat)

    with pytest.raises(RuntimeError, match="^OpenRouter временно ограничил запросы"):
        asyncio.run(main.improve_prompt_openrouter(
            main.ImprovePromptRequest(prompt="test"),
            main.DEFAULT_ASSISTANT_MODELS_CONFIG["improve"],
        ))


def test_prompt_improvement_preserves_invalid_success_payload_error(monkeypatch):
    async def invalid_chat(**_kwargs):
        return 200, ["not", "a", "dict"]

    monkeypatch.setattr(main, "openrouter_api_key", lambda: "configured-secret")
    monkeypatch.setattr(main, "openrouter_headers", lambda: {})
    monkeypatch.setattr(main, "request_openrouter_chat_completion", invalid_chat)

    with pytest.raises(RuntimeError, match=r"^OpenRouter вернул некорректный ответ\.$"):
        asyncio.run(main.improve_prompt_openrouter(
            main.ImprovePromptRequest(prompt="test"),
            main.DEFAULT_ASSISTANT_MODELS_CONFIG["improve"],
        ))


def test_voice_transcription_keeps_openrouter_audio_body_timeout_and_limit(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_chat(**kwargs):
        captured.update(kwargs)
        return 200, {"choices": [{"message": {"content": f"  {'x' * 2105}  "}}]}

    monkeypatch.setattr(main, "openrouter_api_key", lambda: "configured-secret")
    monkeypatch.setattr(main, "openrouter_headers", lambda: {"Authorization": "not-returned"})
    monkeypatch.setattr(main, "request_openrouter_chat_completion", fake_chat)
    config = {"apiModel": "google/gemini-3.1-flash-lite", "requestTimeoutSeconds": 999}

    text, payload = asyncio.run(main.transcribe_audio_openrouter(
        b"audio-bytes",
        "webm",
        "русском",
        config,
    ))

    assert text == "x" * 2000
    assert payload == {"choices": [{"message": {"content": f"  {'x' * 2105}  "}}]}
    assert captured["base_url"] == main.OPENROUTER_BASE_URL
    assert captured["headers"] == {"Authorization": "not-returned"}
    assert captured["timeout_seconds"] == 60
    assert captured["body"] == {
        "model": "google/gemini-3.1-flash-lite",
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Точно расшифруй речь на языке русском. Верни только произнесённый текст без пояснений и кавычек.",
                },
                {
                    "type": "input_audio",
                    "input_audio": {"data": "YXVkaW8tYnl0ZXM=", "format": "webm"},
                },
            ],
        }],
        "temperature": 0,
        "max_tokens": 1000,
    }


def test_voice_transcription_preserves_minimum_timeout_and_trim(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_chat(**kwargs):
        captured.update(kwargs)
        return 200, {"choices": [{"message": {"content": "  распознанный API текст  "}}]}

    monkeypatch.setattr(main, "openrouter_api_key", lambda: "configured-secret")
    monkeypatch.setattr(main, "openrouter_headers", lambda: {})
    monkeypatch.setattr(main, "request_openrouter_chat_completion", fake_chat)

    text, _payload = asyncio.run(main.transcribe_audio_openrouter(
        b"wav",
        "wav",
        "английском",
        {"apiModel": "test/audio", "requestTimeoutSeconds": 1},
    ))

    assert text == "распознанный API текст"
    assert captured["timeout_seconds"] == 3


def test_voice_transcription_without_key_skips_transport(monkeypatch):
    async def unexpected_chat(**_kwargs):
        raise AssertionError("OpenRouter HTTP must not run without a key")

    monkeypatch.setattr(main, "openrouter_api_key", lambda: "")
    monkeypatch.setattr(main, "request_openrouter_chat_completion", unexpected_chat)

    with pytest.raises(RuntimeError, match=r"^OpenRouter API-ключ не настроен\.$"):
        asyncio.run(main.transcribe_audio_openrouter(b"audio", "webm", "русском"))


def test_voice_transcription_preserves_public_provider_error(monkeypatch):
    async def failed_chat(**_kwargs):
        return 429, {"error": {"message": "rate limited"}}

    monkeypatch.setattr(main, "openrouter_api_key", lambda: "configured-secret")
    monkeypatch.setattr(main, "openrouter_headers", lambda: {})
    monkeypatch.setattr(main, "request_openrouter_chat_completion", failed_chat)

    with pytest.raises(RuntimeError, match="^OpenRouter временно ограничил запросы"):
        asyncio.run(main.transcribe_audio_openrouter(
            b"audio",
            "webm",
            "русском",
            main.DEFAULT_ASSISTANT_MODELS_CONFIG["voice"],
        ))


def test_voice_transcription_preserves_invalid_success_payload_error(monkeypatch):
    async def invalid_chat(**_kwargs):
        return 200, ["not", "a", "dict"]

    monkeypatch.setattr(main, "openrouter_api_key", lambda: "configured-secret")
    monkeypatch.setattr(main, "openrouter_headers", lambda: {})
    monkeypatch.setattr(main, "request_openrouter_chat_completion", invalid_chat)

    with pytest.raises(RuntimeError, match=r"^OpenRouter вернул некорректный ответ транскрибации\.$"):
        asyncio.run(main.transcribe_audio_openrouter(
            b"audio",
            "webm",
            "русском",
            main.DEFAULT_ASSISTANT_MODELS_CONFIG["voice"],
        ))


def test_voice_transcription_preserves_empty_text_error(monkeypatch):
    async def empty_chat(**_kwargs):
        return 200, {"choices": [{"message": {"content": "   "}}]}

    monkeypatch.setattr(main, "openrouter_api_key", lambda: "configured-secret")
    monkeypatch.setattr(main, "openrouter_headers", lambda: {})
    monkeypatch.setattr(main, "request_openrouter_chat_completion", empty_chat)

    with pytest.raises(RuntimeError, match=r"^Модель не распознала речь\.$"):
        asyncio.run(main.transcribe_audio_openrouter(
            b"audio",
            "webm",
            "русском",
            main.DEFAULT_ASSISTANT_MODELS_CONFIG["voice"],
        ))


def test_image_model_documents_collect_primary_relative_absolute_and_missing_endpoints():
    seen: list[httpx.Request] = []
    model_a = {"id": "provider/a", "name": "A", "endpoints": "/api/v1/provider/a/endpoints"}
    model_b = {"id": "provider/b", "name": "B", "endpoints": "https://metadata.test/provider/b"}
    model_c = {"id": "provider/c", "name": "C"}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/v1/images/models":
            return httpx.Response(200, json={"data": [model_a, model_b, model_c, {"name": "missing id"}, "invalid"]})
        if request.url.path.endswith("/provider/a/endpoints"):
            return httpx.Response(200, json={"endpoints": [{"provider_tag": "a"}, "invalid"]})
        return httpx.Response(202, json={"endpoints": [{"provider_tag": "b"}]})

    documents = asyncio.run(fetch_openrouter_image_model_documents(
        base_url="https://openrouter.test/api/v1/",
        headers={"Authorization": "Bearer test"},
        timeout_seconds=20,
        max_concurrency=8,
        endpoint_base_url="https://openrouter.test",
        transport=httpx.MockTransport(handler),
    ))

    assert documents == [
        {"model": model_a, "endpoint_status": 200, "endpoints": [{"provider_tag": "a"}]},
        {"model": model_b, "endpoint_status": 202, "endpoints": [{"provider_tag": "b"}]},
        {"model": model_c, "endpoint_status": None, "endpoints": []},
    ]
    assert {request.url.host for request in seen} == {"openrouter.test", "metadata.test"}
    assert all(request.headers["Authorization"] == "Bearer test" for request in seen)


def test_image_model_documents_swallow_only_endpoint_failures():
    models = [
        {"id": "provider/http-error", "endpoints": "/http-error"},
        {"id": "provider/json-error", "endpoints": "/json-error"},
        {"id": "provider/network-error", "endpoints": "/network-error"},
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/images/models"):
            return httpx.Response(200, json={"data": models})
        if request.url.path.endswith("/http-error"):
            return httpx.Response(503, json={"endpoints": [{"provider_tag": "unusable"}]})
        if request.url.path.endswith("/json-error"):
            return httpx.Response(200, content=b"not-json")
        raise httpx.ConnectError("endpoint unavailable", request=request)

    documents = asyncio.run(fetch_openrouter_image_model_documents(
        base_url="https://openrouter.test/api/v1",
        headers={},
        transport=httpx.MockTransport(handler),
    ))

    assert documents[0] == {
        "model": models[0],
        "endpoint_status": 503,
        "endpoints": [{"provider_tag": "unusable"}],
    }
    assert documents[1] == {"model": models[1], "endpoint_status": None, "endpoints": []}
    assert documents[2] == {"model": models[2], "endpoint_status": None, "endpoints": []}


def test_image_model_documents_preserve_primary_http_and_json_errors():
    async def http_error(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(fetch_openrouter_image_model_documents(
            base_url="https://openrouter.test/api/v1",
            headers={},
            transport=httpx.MockTransport(http_error),
        ))

    async def invalid_json(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    with pytest.raises(json.JSONDecodeError):
        asyncio.run(fetch_openrouter_image_model_documents(
            base_url="https://openrouter.test/api/v1",
            headers={},
            transport=httpx.MockTransport(invalid_json),
        ))


def test_image_model_documents_enforce_concurrency_limit():
    active = 0
    peak = 0
    rows = [{"id": f"provider/{index}", "endpoints": f"/endpoint/{index}"} for index in range(6)]

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        if request.url.path.endswith("/images/models"):
            return httpx.Response(200, json={"data": rows})
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return httpx.Response(200, json={"endpoints": []})

    asyncio.run(fetch_openrouter_image_model_documents(
        base_url="https://openrouter.test/api/v1",
        headers={},
        max_concurrency=2,
        transport=httpx.MockTransport(handler),
    ))

    assert peak == 2


def test_main_image_capability_wrapper_preserves_policy_sort_and_cache(monkeypatch):
    captured: dict[str, object] = {}
    endpoint_small = {"provider_tag": "small", "supported_parameters": {"resolution": {}}}
    endpoint_large = {
        "provider_name": "Large Provider",
        "provider_tag": "large",
        "supported_parameters": {"resolution": {}, "seed": {}, "input_references": {"max": 2}},
    }
    documents = [
        {
            "model": {"id": "z/unverified", "name": "Zulu", "architecture": {"output_modalities": ["image"]}},
            "endpoint_status": None,
            "endpoints": [],
        },
        {
            "model": {"id": "a/verified", "name": "Alpha", "architecture": {"input_modalities": ["text"], "output_modalities": ["image"]}},
            "endpoint_status": 200,
            "endpoints": [endpoint_small, endpoint_large],
        },
    ]

    async def fake_fetch(**kwargs):
        captured.update(kwargs)
        return documents

    monkeypatch.setattr(main, "fetch_openrouter_image_model_documents", fake_fetch)
    monkeypatch.setattr(main, "openrouter_api_key", lambda: "")
    monkeypatch.setattr(main.time, "monotonic", lambda: 750.0)
    monkeypatch.setattr(main, "_openrouter_capability_cache", {"ts": 0.0, "models": []})

    models = asyncio.run(main.fetch_openrouter_image_capabilities(force=True))

    assert [model["id"] for model in models] == ["a/verified", "z/unverified"]
    assert models[0]["endpointVerified"] is True
    assert models[0]["providerTag"] == "large"
    assert models[0]["parameters"] == ["input_references", "resolution", "seed"]
    assert models[1]["endpointVerified"] is False
    assert captured == {
        "base_url": main.OPENROUTER_BASE_URL,
        "headers": {"Content-Type": "application/json"},
        "timeout_seconds": 20,
        "max_concurrency": 8,
    }
    assert main._openrouter_capability_cache == {"ts": 750.0, "models": models}


def test_main_image_capability_wrapper_uses_fresh_cache_without_http(monkeypatch):
    expected = [{"id": "cached/image", "name": "Cached"}]

    async def unexpected_fetch(**_kwargs):
        raise AssertionError("fresh capability cache must avoid OpenRouter HTTP")

    monkeypatch.setattr(main, "fetch_openrouter_image_model_documents", unexpected_fetch)
    monkeypatch.setattr(main.time, "monotonic", lambda: 1_000.0)
    monkeypatch.setattr(main, "_openrouter_capability_cache", {"ts": 999.0, "models": expected})

    assert asyncio.run(main.fetch_openrouter_image_capabilities()) == expected
