"""Characterization tests for the isolated Ollama discovery boundary."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

import main
from app.integrations.ollama import (
    ensure_ollama_model_resident,
    fetch_ollama_models_status,
    fetch_ollama_residency_status,
    ollama_base_url,
    request_ollama_chat_message,
    unload_ollama_model,
)


def test_voice_defaults_to_resident_local_ollama() -> None:
    voice = main.DEFAULT_ASSISTANT_MODELS_CONFIG["voice"]

    assert voice["route"] == "local"
    assert voice["localModel"] == "gemma4:12b"


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


def test_residency_status_reads_loaded_models_only():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/ps"
        return httpx.Response(200, json={"models": [{"name": "gemma4:12b", "size_vram": 123}]})

    result = asyncio.run(fetch_ollama_residency_status(base_url="http://ollama.test", transport=httpx.MockTransport(handler)))
    assert result["ok"] is True
    assert result["models"][0]["name"] == "gemma4:12b"


def test_ensure_resident_loads_cold_model_and_verifies_it():
    paths: list[str] = []
    checks = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal checks
        paths.append(request.url.path)
        if request.url.path == "/api/ps":
            checks += 1
            return httpx.Response(200, json={"models": [] if checks == 1 else [{"name": "gemma4:12b", "size_vram": 99}]})
        body = json.loads(request.content)
        assert body["model"] == "gemma4:12b"
        assert body["keep_alive"] == -1
        return httpx.Response(200, json={"message": {"content": "готово"}})

    result = asyncio.run(ensure_ollama_model_resident(model="gemma4:12b", transport=httpx.MockTransport(handler)))
    assert result["ok"] is True
    assert result["sizeVram"] == 99
    assert paths == ["/api/ps", "/api/chat", "/api/ps"]


def test_ensure_resident_does_not_reload_warm_model():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/ps"
        return httpx.Response(200, json={"models": [{"name": "gemma4:12b", "size_vram": 99}]})

    result = asyncio.run(ensure_ollama_model_resident(model="gemma4:12b", transport=httpx.MockTransport(handler)))
    assert result["alreadyResident"] is True


def test_unload_model_uses_zero_keep_alive():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/generate"
        assert json.loads(request.content) == {"model": "gemma4:12b", "stream": False, "keep_alive": 0}
        return httpx.Response(200, json={"done": True})

    asyncio.run(unload_ollama_model(model="gemma4:12b", transport=httpx.MockTransport(handler)))


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
    assert body["keep_alive"] == -1
    assert body["options"] == {"temperature": 0.25, "num_predict": 500}
    assert body["format"]["required"] == ["improved_prompt"]
    assert body["messages"][0]["role"] == "system"
    assert "Ответ верни на русском" in body["messages"][0]["content"]
    assert body["messages"][1] == {
        "role": "user",
        "content": '{"prompt": "исходный запрос", "technical_context": "технический контекст"}',
    }


def test_voice_transcription_normalizes_audio_and_keeps_ollama_body(monkeypatch):
    captured: dict[str, object] = {}

    def fake_normalize(audio, suffix):
        captured.update({"sourceAudio": audio, "sourceSuffix": suffix})
        return b"normalized-wav"

    async def fake_chat(*, body, timeout_seconds):
        captured.update({"body": body, "timeout": timeout_seconds})
        return f"  {'x' * 2105}  ", {"done": True}

    monkeypatch.setattr(main, "normalize_audio_to_wav", fake_normalize)
    monkeypatch.setattr(main, "request_ollama_chat_message", fake_chat)
    config = {"localModel": "gemma4:12b", "requestTimeoutSeconds": 999}

    text, payload = asyncio.run(main.transcribe_audio_ollama(b"webm-audio", "webm", "русском", config))

    assert text == "x" * 2000
    assert payload == {"done": True}
    assert captured["sourceAudio"] == b"webm-audio"
    assert captured["sourceSuffix"] == "webm"
    assert captured["timeout"] == 180
    body = captured["body"]
    assert isinstance(body, dict)
    assert body == {
        "model": "gemma4:12b",
        "stream": False,
        "think": False,
        "keep_alive": -1,
        "messages": [{
            "role": "user",
            "images": ["bm9ybWFsaXplZC13YXY="],
            "content": "Транскрибируй речь на русском языке. Верни только произнесённый текст без пояснений, кавычек и переносов строк.",
        }],
        "options": {"temperature": 0, "num_predict": 256, "num_ctx": 8192},
    }


def test_voice_transcription_keeps_wav_bytes_and_minimum_timeout(monkeypatch):
    captured: dict[str, object] = {}

    def unexpected_normalize(_audio, _suffix):
        raise AssertionError("WAV input must not be normalized")

    async def fake_chat(*, body, timeout_seconds):
        captured.update({"body": body, "timeout": timeout_seconds})
        return "  распознанный текст  ", {"done": True}

    monkeypatch.setattr(main, "normalize_audio_to_wav", unexpected_normalize)
    monkeypatch.setattr(main, "request_ollama_chat_message", fake_chat)

    text, _payload = asyncio.run(
        main.transcribe_audio_ollama(
            b"wav-bytes",
            "wav",
            "английском",
            {"localModel": "gemma4:12b", "requestTimeoutSeconds": 1},
        )
    )

    assert text == "распознанный текст"
    assert captured["timeout"] == 10
    assert captured["body"]["messages"][0]["images"] == ["d2F2LWJ5dGVz"]


def test_voice_transcription_rejects_model_without_audio_encoder_before_work(monkeypatch):
    def unexpected_normalize(_audio, _suffix):
        raise AssertionError("normalization must not run")

    async def unexpected_chat(**_kwargs):
        raise AssertionError("Ollama request must not run")

    monkeypatch.setattr(main, "normalize_audio_to_wav", unexpected_normalize)
    monkeypatch.setattr(main, "request_ollama_chat_message", unexpected_chat)

    with pytest.raises(RuntimeError, match=r"^Модель gemma4:31b-cloud не имеет аудиоэнкодера\.$"):
        asyncio.run(
            main.transcribe_audio_ollama(
                b"audio",
                "webm",
                "русском",
                {"localModel": "gemma4:31b-cloud"},
            )
        )


def test_voice_transcription_preserves_empty_model_error(monkeypatch):
    async def fake_chat(*, body, timeout_seconds):
        return "  ", {"done": True}

    monkeypatch.setattr(main, "request_ollama_chat_message", fake_chat)

    with pytest.raises(RuntimeError, match=r"^Локальная модель не распознала речь\.$"):
        asyncio.run(
            main.transcribe_audio_ollama(
                b"wav",
                "wav",
                "русском",
                {"localModel": "gemma4:12b"},
            )
        )
