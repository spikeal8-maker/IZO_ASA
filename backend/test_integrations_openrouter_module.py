"""Characterization tests for the isolated OpenRouter text-model catalog."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

import main
from app.integrations.openrouter import (
    extract_openrouter_error_payload,
    extract_openrouter_generation_cost,
    fetch_openrouter_key_details,
    fetch_openrouter_image_model_documents,
    fetch_openrouter_audio_input_models,
    fetch_openrouter_text_models,
    fetch_openrouter_video_models,
    format_openrouter_public_error,
    is_openrouter_size_error,
    normalize_openrouter_endpoint_capability,
    normalize_openrouter_image_response_metadata,
    normalize_openrouter_model_capability,
    normalize_openrouter_video_config,
    openrouter_error_message,
    parse_openrouter_audio_input_models,
    parse_openrouter_text_models,
    parse_openrouter_video_models,
    request_openrouter_chat_completion,
    select_openrouter_first_image,
)


TEXT_ARCHITECTURE = {"input_modalities": ["text"], "output_modalities": ["text"]}
AUDIO_ARCHITECTURE = {"input_modalities": ["text", "audio"], "output_modalities": ["text"]}


def test_audio_model_parser_only_keeps_audio_input_and_sorts_by_price():
    payload = {"data": [
        {"id": "audio/expensive", "name": "Expensive", "architecture": AUDIO_ARCHITECTURE, "pricing": {"prompt": "0.000002", "completion": "0.000003"}},
        {"id": "audio/cheap", "name": "Cheap", "architecture": AUDIO_ARCHITECTURE, "pricing": {"prompt": "0.0000001", "completion": "0.0000002"}},
        {"id": "openrouter/auto", "name": "Auto Router", "architecture": AUDIO_ARCHITECTURE, "pricing": {"prompt": "-1", "completion": "-1"}},
        {"id": "text/only", "name": "Text", "architecture": TEXT_ARCHITECTURE, "pricing": {}},
    ]}

    assert [model["id"] for model in parse_openrouter_audio_input_models(payload)] == ["audio/cheap", "audio/expensive"]
    assert parse_openrouter_audio_input_models(payload)[0]["inputPerMillionUsd"] == 0.1


def test_audio_model_fetch_uses_modality_filters():
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": [{"id": "audio/model", "architecture": AUDIO_ARCHITECTURE}]})

    result = asyncio.run(fetch_openrouter_audio_input_models(
        base_url="https://openrouter.test/api/v1/",
        headers={"Authorization": "Bearer test"},
        transport=httpx.MockTransport(handler),
    ))

    assert result[0]["id"] == "audio/model"
    assert dict(seen[0].url.params) == {"input_modalities": "audio", "output_modalities": "text"}


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


def test_video_model_parser_normalizes_capabilities_prices_and_evidence():
    payload = {"data": [{
        "id": "vendor/video-pro",
        "name": "Video Pro",
        "description": "Creates video from text, frames, or a set of reference images.",
        "created": "invalid",
        "supported_resolutions": ["720p", "1080p"],
        "supported_aspect_ratios": ["16:9", "9:16"],
        "supported_sizes": ["1280x720"],
        "supported_durations": [10, "5", 0, "bad", 5],
        "supported_frame_images": ["first_frame", "last_frame"],
        "generate_audio": True,
        "seed": False,
        "pricing_skus": {"duration_seconds_720p": "0.08", "bad": "unknown", "negative": -1},
        "allowed_passthrough_parameters": ["seed", "generate_audio"],
    }, {"name": "missing id"}, "bad-row"]}

    models = parse_openrouter_video_models(payload)

    assert len(models) == 1
    model = models[0]
    assert model["id"] == "vendor/video-pro"
    assert model["created"] == 0
    assert model["supportedDurations"] == [5, 10]
    assert model["pricingSkus"] == {"duration_seconds_720p": 0.08}
    assert model["modes"] == ["text_to_video", "image_to_video", "first_last_frame", "reference_to_video"]
    assert model["referenceEvidence"] == "description"


def test_video_model_fetch_uses_dedicated_catalog_endpoint():
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": [{"id": "vendor/video", "name": "Video"}]})

    result = asyncio.run(fetch_openrouter_video_models(
        base_url="https://openrouter.test/api/v1/",
        headers={"Authorization": "Bearer test-token"},
        transport=httpx.MockTransport(handler),
    ))

    assert result[0]["id"] == "vendor/video"
    assert seen[0].url.path == "/api/v1/videos/models"
    assert seen[0].headers["authorization"] == "Bearer test-token"


def test_video_model_parser_tolerates_empty_and_malformed_payloads():
    assert parse_openrouter_video_models(None) == []
    assert parse_openrouter_video_models({"data": {}}) == []


def test_video_config_keeps_only_catalog_modes_tiers_and_models():
    catalog = [
        {"id": "vendor/text", "modes": ["text_to_video"]},
        {"id": "vendor/image", "modes": ["text_to_video", "image_to_video"]},
    ]
    config = normalize_openrouter_video_config({
        "enabled": {
            "text_to_video": ["vendor/text", "missing/model"],
            "unknown_mode": ["vendor/text"],
        },
        "access": {
            "text_to_video": {"mini": ["vendor/image"], "free": ["vendor/text"]},
            "image_to_video": {"pro": ["vendor/image", "vendor/text"]},
        },
    }, catalog)

    assert config == {
        "enabled": {
            "text_to_video": ["vendor/image", "vendor/text"],
            "image_to_video": ["vendor/image"],
        },
        "access": {
            "text_to_video": {"mini": ["vendor/image"]},
            "image_to_video": {"pro": ["vendor/image"]},
        },
    }


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


def test_image_model_capability_normalization_preserves_exact_legacy_shape():
    parameters = {
        "input_references": {"type": "range", "max": "4"},
        "background": {"values": ["auto", "transparent", 123]},
        "seed": {"type": "integer"},
        "quality": {"type": "enum"},
        "aspect_ratio": {"type": "enum"},
        "resolution": {"type": "enum"},
        "mask": {"type": "image"},
        "canvas": {"type": "image"},
        "n": {"max": 2},
    }

    capability = normalize_openrouter_model_capability({
        "id": "provider/editor",
        "description": "Editor",
        "architecture": {
            "input_modalities": ["image", 7, "text"],
            "output_modalities": ["image", None],
        },
        "supported_parameters": parameters,
        "supports_streaming": 1,
    })

    assert capability == {
        "id": "provider/editor",
        "name": "provider/editor",
        "description": "Editor",
        "inputModalities": ["image", "text"],
        "outputModalities": ["image"],
        "parameters": sorted(parameters),
        "parameterDescriptors": parameters,
        "maxInputReferences": 4,
        "supportsStreaming": True,
        "modes": [
            "edit",
            "image_to_image",
            "inpaint",
            "outpaint",
            "paint",
            "remove_background",
            "text_to_image",
        ],
        "features": {
            "seed": True,
            "quality": True,
            "aspectRatio": True,
            "resolution": True,
            "transparentBackground": True,
            "multipleOutputs": True,
        },
    }


@pytest.mark.parametrize("maximum", [-3, "invalid", None, []])
def test_image_model_capability_normalization_sanitizes_reference_limit(maximum):
    capability = normalize_openrouter_model_capability({
        "id": "provider/basic",
        "architecture": {"input_modalities": ["text"], "output_modalities": ["image"]},
        "supported_parameters": {"input_references": {"max": maximum}},
    })

    assert capability["maxInputReferences"] == 0
    assert capability["modes"] == ["text_to_image"]


def test_image_model_capability_requires_image_output_for_generation_modes():
    capability = normalize_openrouter_model_capability({
        "id": "provider/text",
        "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
        "supported_parameters": {
            "input_references": {"max": 4},
            "mask": {},
            "outpaint": {},
            "background": {"values": ["transparent"]},
        },
    })

    assert capability["modes"] == []
    assert capability["maxInputReferences"] == 4
    assert capability["features"]["transparentBackground"] is True


def test_image_endpoint_capability_uses_endpoint_parameters_and_safe_metadata_lists():
    capability = normalize_openrouter_endpoint_capability(
        {
            "id": "provider/image",
            "architecture": {"input_modalities": ["text"], "output_modalities": ["image"]},
            "supported_parameters": {"resolution": {"values": ["2K"]}},
        },
        {
            "provider_name": "Pinned",
            "provider_slug": "pinned",
            "provider_tag": "pinned-tag",
            "supported_parameters": {"seed": {"type": "integer"}},
            "pricing": {"invalid": True},
            "allowed_passthrough_parameters": "invalid",
        },
    )

    assert capability["parameters"] == ["seed"]
    assert capability["features"]["resolution"] is False
    assert capability["features"]["seed"] is True
    assert capability["endpointVerified"] is True
    assert capability["providerName"] == "Pinned"
    assert capability["providerSlug"] == "pinned"
    assert capability["providerTag"] == "pinned-tag"
    assert capability["pricing"] == []
    assert capability["allowedPassthroughParameters"] == []


def test_main_capability_compatibility_wrappers_delegate(monkeypatch):
    model = {"id": "provider/model"}
    endpoint = {"provider_tag": "tag"}
    model_result = {"kind": "model"}
    endpoint_result = {"kind": "endpoint"}
    seen: list[tuple[object, ...]] = []

    def fake_model(value):
        seen.append(("model", value))
        return model_result

    def fake_endpoint(model_value, endpoint_value):
        seen.append(("endpoint", model_value, endpoint_value))
        return endpoint_result

    monkeypatch.setattr(main, "normalize_openrouter_model_capability", fake_model)
    monkeypatch.setattr(main, "normalize_openrouter_endpoint_capability", fake_endpoint)

    assert main.openrouter_model_capability(model) is model_result
    assert main.openrouter_endpoint_capability(model, endpoint) is endpoint_result
    assert seen == [("model", model), ("endpoint", model, endpoint)]


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"cost": 0, "total_cost": 5}, 0.0),
        ({"cost": "invalid", "total_cost": "1.25"}, 1.25),
        ({"total_cost_usd": 2}, 2.0),
        ({"usage": {"cost": "0.75"}}, 0.75),
        ({"usage": {"cost": "invalid", "total_cost": 3}}, 3.0),
        ({"usage": {"total_cost_usd": "4.5"}}, 4.5),
        ({"usage": {}}, None),
        ({"usage": "invalid"}, None),
    ],
)
def test_generation_cost_parser_preserves_precedence_and_numeric_conversion(payload, expected):
    assert extract_openrouter_generation_cost(payload) == expected


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"data": [{"b64_json": "data-value"}, {"url": "second"}]}, {"b64_json": "data-value"}),
        ({"data": ["invalid"], "images": [{"url": "image-dict"}]}, {"url": "image-dict"}),
        ({"images": ["https://images.test/one.png"]}, {"url": "https://images.test/one.png"}),
        ({"output": [{"url": "output-url"}]}, {"url": "output-url"}),
        ({"output": [{"b64_json": "output-b64"}]}, {"b64_json": "output-b64"}),
        ({"output": [{"content": [{"type": "text"}, {"url": "nested-url"}]}]}, {"url": "nested-url"}),
    ],
)
def test_first_image_parser_preserves_supported_response_shapes(payload, expected):
    assert select_openrouter_first_image(payload) == expected


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": []},
        {"images": [7]},
        {"output": [{"content": [{"type": "text", "text": "none"}]}]},
    ],
)
def test_first_image_parser_preserves_missing_image_error(payload):
    with pytest.raises(RuntimeError, match="OpenRouter не вернул изображение в ответе"):
        select_openrouter_first_image(payload)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"error": "plain error"}, "plain error"),
        ({"error": {"message": "bad request"}}, "bad request"),
        ({"error": {"message": "bad request", "metadata": {"provider_name": "Provider"}}}, "Provider: bad request"),
        ({"error": {"error": "nested error"}}, "nested error"),
        ({"error": {"code": 500}}, "{'code': 500}"),
        ({"message": "top-level only"}, "{'message': 'top-level only'}"),
        ({}, ""),
    ],
)
def test_error_parser_preserves_provider_and_fallback_shapes(payload, expected):
    assert extract_openrouter_error_payload(payload) == payload.get("error")
    assert openrouter_error_message(payload) == expected


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("invalid size requested", True),
        ("IMAGE SIZE rejected", True),
        ("unsupported aspect_ratio", True),
        ("invalid_value for width", True),
        ("too many pixels", True),
        ("authentication failed", False),
    ],
)
def test_size_error_classifier_preserves_markers(message, expected):
    assert is_openrouter_size_error({"error": {"message": message}}) is expected


def test_main_response_parser_compatibility_wrappers_delegate(monkeypatch):
    payload = {"value": "sentinel"}
    image_result = {"url": "sentinel"}
    seen: list[tuple[object, ...]] = []

    monkeypatch.setattr(main, "extract_openrouter_generation_cost", lambda value: seen.append(("cost", value)) or 1.5)
    monkeypatch.setattr(main, "select_openrouter_first_image", lambda value: seen.append(("image", value)) or image_result)
    monkeypatch.setattr(main, "extract_openrouter_error_payload", lambda value: seen.append(("payload", value)) or "error-payload")
    monkeypatch.setattr(main, "openrouter_error_message", lambda value: seen.append(("message", value)) or "error-message")
    monkeypatch.setattr(main, "is_openrouter_size_error", lambda value: seen.append(("size", value)) or True)

    assert main._openrouter_generation_cost(payload) == 1.5
    assert main._openrouter_first_image(payload) is image_result
    assert main._openrouter_error_payload(payload) == "error-payload"
    assert main._openrouter_error_message(payload) == "error-message"
    assert main._openrouter_is_size_error(payload) is True
    assert seen == [
        ("cost", payload),
        ("image", payload),
        ("payload", payload),
        ("message", payload),
        ("size", payload),
    ]


@pytest.mark.parametrize(
    ("status", "payload", "expected"),
    [
        (
            400,
            {"error": {"message": "invalid size requested"}},
            "Модель не приняла выбранный формат изображения. Попробуйте квадратный формат или другую модель.",
        ),
        (
            401,
            {"error": {"message": "invalid size requested"}},
            "Модель не приняла выбранный формат изображения. Попробуйте квадратный формат или другую модель.",
        ),
        (401, {"error": "unauthorized"}, "OpenRouter не принял API-ключ или доступ к модели закрыт."),
        (403, {"error": "forbidden"}, "OpenRouter не принял API-ключ или доступ к модели закрыт."),
        (429, {"error": "rate limited"}, "OpenRouter временно ограничил запросы. Подождите немного и попробуйте снова."),
    ],
)
def test_public_error_mapping_preserves_precedence_and_special_statuses(status, payload, expected):
    assert format_openrouter_public_error(
        status,
        payload,
        truncate=lambda _message, _limit: pytest.fail("special errors must not call truncation"),
    ) == expected


def test_public_error_mapping_preserves_provider_message_and_truncation_limit():
    seen: list[tuple[str, int]] = []

    error = format_openrouter_public_error(
        500,
        {"error": {"message": "provider failure", "metadata": {"provider_name": "Provider"}}},
        truncate=lambda message, limit: seen.append((message, limit)) or "trimmed-message",
    )

    assert error == "OpenRouter вернул ошибку 500: trimmed-message"
    assert seen == [("Provider: provider failure", 220)]


def test_image_response_metadata_preserves_safe_fields_and_cost_precedence():
    data = {
        "id": "primary-id",
        "response_id": "fallback-id",
        "usage": {"images": 1},
        "cost": "0.125",
        "provider": "provider-name",
        "data": [{"b64_json": "secret-image-bytes"}],
        "images": ["secret-image-url"],
        "output": [{"url": "secret-output-url"}],
    }

    metadata = normalize_openrouter_image_response_metadata(data)

    assert metadata == {
        "response_id": "primary-id",
        "usage": {"images": 1},
        "cost_usd": 0.125,
        "raw": {
            "id": "primary-id",
            "response_id": "fallback-id",
            "usage": {"images": 1},
            "cost": "0.125",
            "provider": "provider-name",
        },
    }


@pytest.mark.parametrize("usage", [None, [], "invalid"])
def test_image_response_metadata_sanitizes_usage_and_uses_fallback_id(usage):
    metadata = normalize_openrouter_image_response_metadata({
        "id": "",
        "response_id": "fallback-id",
        "usage": usage,
    })

    assert metadata["response_id"] == "fallback-id"
    assert metadata["usage"] == {}
    assert metadata["cost_usd"] is None
    assert metadata["raw"]["usage"] == usage


def test_main_public_error_wrapper_keeps_application_truncator(monkeypatch):
    payload = {"error": "sentinel"}
    captured: dict[str, object] = {}

    def fake_format(status, data, *, truncate):
        captured.update({"status": status, "data": data, "truncate": truncate})
        return "mapped-error"

    monkeypatch.setattr(main, "format_openrouter_public_error", fake_format)

    assert main._openrouter_public_error(500, payload) == "mapped-error"
    assert captured == {
        "status": 500,
        "data": payload,
        "truncate": main.truncate_admin_text,
    }
