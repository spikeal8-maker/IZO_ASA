from __future__ import annotations

import asyncio
import json

from app.api.routers import phone_chat
from app.api.routers.phone_chat import PhoneChatDependencies, PhoneChatRequest


def _deps() -> PhoneChatDependencies:
    return PhoneChatDependencies(
        require_trusted_user=lambda _request: {},
        assistant_models_config=lambda: {},
        openrouter_headers=lambda: {"Authorization": "Bearer test"},
        record_openrouter_availability=lambda _status: None,
        record_event=lambda *args, **kwargs: None,
        openrouter_text_models=lambda: [],
        charge_tokens=lambda **kwargs: {},
        refund_tokens=lambda **kwargs: True,
    )


def _config() -> dict[str, object]:
    return {
        "localModel": "gemma4:12b",
        "apiModel": "openai/gpt-4.1-mini",
        "localTimeoutSeconds": 45,
        "apiTimeoutSeconds": 30,
    }


def test_tool_call_accepts_ollama_and_openrouter_arguments() -> None:
    local = {"function": {"name": "web_search", "arguments": {"query": "новости"}}}
    cloud = {"id": "call_1", "function": {"name": "generate_image", "arguments": '{"prompt":"кот","aspect_ratio":"9:16"}'}}

    assert phone_chat._tool_call(local)[:2] == ("web_search", {"query": "новости"})
    assert phone_chat._tool_call(cloud) == ("generate_image", {"prompt": "кот", "aspect_ratio": "9:16"}, "call_1")


def test_web_sources_are_safe_deduplicated_and_bounded() -> None:
    payload = {
        "choices": [{"message": {"annotations": [
            {"type": "url_citation", "url_citation": {"url": "https://example.com/a", "title": "Источник"}},
            {"type": "url_citation", "url_citation": {"url": "https://example.com/a", "title": "Дубликат"}},
            {"type": "url_citation", "url_citation": {"url": "javascript:alert(1)", "title": "Опасная ссылка"}},
        ]}}],
    }

    assert phone_chat._web_sources(payload) == [{"url": "https://example.com/a", "title": "Источник"}]


def test_current_weather_always_requires_web_search() -> None:
    weather = PhoneChatRequest(messages=[{"role": "user", "content": "Какая сейчас погода в Москве?"}])
    general = PhoneChatRequest(messages=[{"role": "user", "content": "Почему меняется погода?"}])

    assert phone_chat._required_web_query(weather) == "Какая сейчас погода в Москве?"
    assert phone_chat._required_web_query(general) == ""


def test_local_chat_prefetches_weather_even_if_model_does_not_call_tool(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_tool(name, arguments, deps, config):
        assert name == "web_search"
        return {"ok": True, "query": arguments["query"], "summary": "В Москве +20.", "sources": []}, {"usage": {"cost": 0.001}}

    async def fake_ollama(*, body, timeout_seconds):
        captured["messages"] = body["messages"]
        return "Сейчас в Москве +20 °C.", {"message": {"role": "assistant", "content": "Сейчас в Москве +20 °C."}}

    monkeypatch.setattr(phone_chat, "_execute_tool", fake_tool)
    monkeypatch.setattr(phone_chat, "request_ollama_chat_message", fake_ollama)
    _reply, payload, _model = asyncio.run(phone_chat.phone_chat_ollama(
        PhoneChatRequest(messages=[{"role": "user", "content": "Какая сейчас погода в Москве?"}]),
        _deps(),
        _config(),
    ))

    assert payload["_izo_tool_runs"][0]["name"] == "web_search"
    assert captured["messages"][-1]["role"] == "tool"


def test_local_chat_executes_image_tool_then_returns_answer(monkeypatch) -> None:
    requests: list[dict[str, object]] = []

    async def fake_ollama(*, body, timeout_seconds):
        requests.append(body)
        if len(requests) == 1:
            return "", {"message": {"role": "assistant", "content": "", "tool_calls": [{
                "function": {"name": "generate_image", "arguments": {"prompt": "красная кружка", "aspect_ratio": "1:1"}},
            }]}}
        return "Запускаю создание изображения.", {"message": {"role": "assistant", "content": "Запускаю создание изображения."}}

    monkeypatch.setattr(phone_chat, "request_ollama_chat_message", fake_ollama)
    reply, payload, model = asyncio.run(phone_chat.phone_chat_ollama(
        PhoneChatRequest(messages=[{"role": "user", "content": "Создай красную кружку"}]),
        _deps(),
        _config(),
    ))

    assert reply == "Запускаю создание изображения."
    assert model == "gemma4:12b"
    assert payload["_izo_tool_runs"] == [{
        "name": "generate_image", "ok": True, "status": "requested",
        "prompt": "красная кружка", "aspectRatio": "1:1",
    }]
    assert requests[0]["tools"] == phone_chat.PHONE_CHAT_TOOLS
    tool_message = requests[1]["messages"][-1]
    assert tool_message["role"] == "tool"
    assert json.loads(tool_message["content"])["status"] == "requested"


def test_web_search_uses_openrouter_server_tool_and_returns_sources(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_openrouter(*, base_url, headers, body, timeout_seconds):
        captured["body"] = body
        return 200, {
            "choices": [{"message": {
                "content": "Актуальный ответ.",
                "annotations": [{"type": "url_citation", "url_citation": {
                    "url": "https://example.com/current", "title": "Текущий источник",
                }}],
            }}],
            "usage": {"cost": 0.001},
        }

    monkeypatch.setattr(phone_chat, "request_openrouter_chat_completion", fake_openrouter)
    result, payload = asyncio.run(phone_chat._web_search("актуальный запрос", _deps(), _config()))

    assert result == {
        "ok": True,
        "query": "актуальный запрос",
        "summary": "Актуальный ответ.",
        "sources": [{"url": "https://example.com/current", "title": "Текущий источник"}],
    }
    assert payload["usage"]["cost"] == 0.001
    assert captured["body"]["tools"] == [{
        "type": "openrouter:web_search", "max_total_results": 5, "search_context_size": "medium",
    }]
