from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError

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
        request_lifecycle=None,
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


def test_tool_choice_rejects_unknown_tools_before_routing() -> None:
    with pytest.raises(ValidationError):
        PhoneChatRequest(
            messages=[{"role": "user", "content": "Сделай видео"}],
            toolChoice="generate_video",
        )


@pytest.mark.parametrize(("text", "expected"), [
    ("Вертикальный постер 9 на 16", "9:16"),
    ("Горизонтальный кадр 16/9", "16:9"),
    ("Фотография 3 x 2", "3:2"),
    ("Квадратная обложка", "1:1"),
    ("Квадратная обложка альбома", "1:1"),
    ("Квадратный портрет кота", "1:1"),
    ("Портрет кота", "1:1"),
    ("Портретная ориентация", "9:16"),
    ("Альбомная ориентация", "16:9"),
    ("Не квадрат, сделай горизонтально", "16:9"),
    ("Горизонтально, только не квадрат", "16:9"),
    ("Квадрат, только не горизонтально", "1:1"),
    ("Landscape, not square", "16:9"),
    ("Square, not landscape", "1:1"),
    ("Квадрат без рамки", "1:1"),
    ("Без рамки горизонтальное изображение", "16:9"),
])
def test_forced_image_aspect_ratio_normalizes_explicit_user_format(text: str, expected: str) -> None:
    request = PhoneChatRequest(messages=[{"role": "user", "content": text}], toolChoice="generate_image")

    assert phone_chat._requested_image_aspect_ratio(request) == expected


@pytest.mark.parametrize("correction", [
    "Только не 16:9", "16:9 не надо", "16:9. Вообще не надо",
    "квадрат не нужен", "Square is not needed",
])
def test_negated_new_image_format_does_not_resurrect_earlier_choice(correction: str) -> None:
    request = PhoneChatRequest(
        messages=[
            {"role": "user", "content": "Сделай изображение 16:9"},
            {"role": "assistant", "content": "Хорошо."},
            {"role": "user", "content": correction},
        ],
        toolChoice="generate_image",
    )

    assert phone_chat._explicit_image_aspect_ratio(request) is None
    assert phone_chat._forced_image_model_arguments(request, {
        "prompt": "готовый самостоятельный prompt", "aspect_ratio": "3:2",
    })["aspect_ratio"] == "3:2"


def test_multiple_affirmative_ratios_defer_to_context_aware_provider() -> None:
    request = PhoneChatRequest(
        messages=[{"role": "user", "content": "Создай квадратный постер с экраном 16:9"}],
        toolChoice="generate_image",
    )

    assert phone_chat._explicit_image_aspect_ratio(request) is None
    assert phone_chat._forced_image_model_arguments(request, {
        "prompt": "квадратный постер с широкоформатным экраном внутри",
        "aspect_ratio": "1:1",
    })["aspect_ratio"] == "1:1"


def test_rejected_only_square_uses_non_rejected_fallback(monkeypatch) -> None:
    calls = 0

    async def fake_ollama(*, body, timeout_seconds):
        nonlocal calls
        calls += 1
        content = "Формат уточнён." if calls == 1 else "Создаю изображение."
        return content, {"message": {"role": "assistant", "content": content}}

    monkeypatch.setattr(phone_chat, "request_ollama_chat_message", fake_ollama)
    request = PhoneChatRequest(
        messages=[{"role": "user", "content": "Квадрат не нужен, сделай изображение маяка"}],
        toolChoice="generate_image",
    )

    _reply, payload, _model = asyncio.run(phone_chat.phone_chat_ollama(request, _deps(), _config()))

    assert payload["_izo_tool_runs"][0]["aspectRatio"] == "3:2"


def test_local_chat_forces_selected_web_search_without_hidden_user_text(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_tool(name, arguments, deps, config):
        assert name == "web_search"
        assert arguments == {"query": "Проверь формулировку"}
        return {"ok": True, "query": arguments["query"], "summary": "Проверено.", "sources": []}, {}

    async def fake_ollama(*, body, timeout_seconds):
        captured["messages"] = body["messages"]
        return "Формулировка проверена.", {"message": {"role": "assistant", "content": "Формулировка проверена."}}

    monkeypatch.setattr(phone_chat, "_execute_tool", fake_tool)
    monkeypatch.setattr(phone_chat, "request_ollama_chat_message", fake_ollama)
    request = PhoneChatRequest(
        messages=[{"role": "user", "content": "Проверь формулировку"}],
        toolChoice="web_search",
    )

    reply, payload, _model = asyncio.run(phone_chat.phone_chat_ollama(request, _deps(), _config()))

    assert reply == "Формулировка проверена."
    assert payload["_izo_tool_runs"][0]["name"] == "web_search"
    messages = captured["messages"]
    assert any(item.get("role") == "user" and item.get("content") == "Проверь формулировку" for item in messages)
    assert all("Обязательно используй инструмент" not in str(item.get("content") or "") for item in messages)


def test_forced_search_uses_context_attachment_and_expands_vague_model_query(monkeypatch) -> None:
    requests: list[dict[str, object]] = []

    async def fake_ollama(*, body, timeout_seconds):
        requests.append(json.loads(json.dumps(body)))
        if len(requests) == 1:
            assert body["messages"][-1]["images"] == ["YQ=="]
            return "", {"message": {"role": "assistant", "content": "", "tool_calls": [{
                "function": {"name": "web_search", "arguments": {
                    "query": "Проверь это",
                }},
            }]}}
        return "Цена проверена.", {"message": {"role": "assistant", "content": "Цена проверена."}}

    async def fake_tool(name, arguments, deps, config):
        assert name == "web_search"
        assert "красная кружка из нужной коллекции" in arguments["query"]
        assert "Проверь её актуальную цену" in arguments["query"]
        assert "Проверь это" in arguments["query"]
        return {"ok": True, "query": arguments["query"], "summary": "Найдено.", "sources": []}, {}

    monkeypatch.setattr(phone_chat, "request_ollama_chat_message", fake_ollama)
    monkeypatch.setattr(phone_chat, "_execute_tool", fake_tool)
    request = PhoneChatRequest(
        messages=[
            {"role": "user", "content": "Это красная кружка из нужной коллекции."},
            {"role": "assistant", "content": "Понял референс."},
            {"role": "user", "content": "Проверь её актуальную цену."},
        ],
        images=["data:image/png;base64,YQ=="],
        toolChoice="web_search",
    )

    reply, payload, _model = asyncio.run(phone_chat.phone_chat_ollama(request, _deps(), _config()))

    assert reply == "Цена проверена."
    assert payload["_izo_tool_runs"][0]["query"].startswith("Найди сведения по контексту:")
    assert [item["function"]["name"] for item in requests[0]["tools"]] == ["web_search"]
    assert "tools" not in requests[1]


def test_forced_search_fallback_expands_vague_query_from_conversation(monkeypatch) -> None:
    calls = 0

    async def fake_ollama(*, body, timeout_seconds):
        nonlocal calls
        calls += 1
        if calls == 1:
            return "Проверь это", {"message": {"role": "assistant", "content": "Проверь это"}}
        return "Проверено.", {"message": {"role": "assistant", "content": "Проверено."}}

    async def fake_tool(name, arguments, deps, config):
        assert name == "web_search"
        assert "модель Aurora X2" in arguments["query"]
        assert "Проверь это" in arguments["query"]
        return {"ok": True, "query": arguments["query"], "summary": "Проверено.", "sources": []}, {}

    monkeypatch.setattr(phone_chat, "request_ollama_chat_message", fake_ollama)
    monkeypatch.setattr(phone_chat, "_execute_tool", fake_tool)
    request = PhoneChatRequest(
        messages=[
            {"role": "user", "content": "Нас интересует модель Aurora X2."},
            {"role": "assistant", "content": "Что именно уточнить?"},
            {"role": "user", "content": "Проверь это."},
        ],
        toolChoice="web_search",
    )

    _reply, payload, _model = asyncio.run(phone_chat.phone_chat_ollama(request, _deps(), _config()))

    assert payload["_izo_tool_runs"][0]["name"] == "web_search"


def test_local_forced_search_rejects_hallucinated_image_tool(monkeypatch) -> None:
    requests: list[dict[str, object]] = []
    executed: list[str] = []

    async def fake_ollama(*, body, timeout_seconds):
        requests.append(json.loads(json.dumps(body)))
        if len(requests) == 1:
            return "", {"message": {"role": "assistant", "content": "", "tool_calls": [{
                "function": {"name": "generate_image", "arguments": {"prompt": "не запускать"}},
            }]}}
        if len(requests) == 2:
            return "", {"message": {"role": "assistant", "content": "", "tool_calls": [{
                "function": {"name": "web_search", "arguments": {"query": "проверяемый факт"}},
            }]}}
        return "Факт проверен.", {"message": {"role": "assistant", "content": "Факт проверен."}}

    async def fake_tool(name, arguments, deps, config):
        executed.append(name)
        return {"ok": True, "query": arguments["query"], "summary": "Найдено.", "sources": []}, {}

    monkeypatch.setattr(phone_chat, "request_ollama_chat_message", fake_ollama)
    monkeypatch.setattr(phone_chat, "_execute_tool", fake_tool)
    request = PhoneChatRequest(
        messages=[{"role": "user", "content": "Проверь факт"}],
        toolChoice="web_search",
    )

    _reply, payload, _model = asyncio.run(phone_chat.phone_chat_ollama(request, _deps(), _config()))

    assert executed == ["web_search"]
    assert [item["name"] for item in payload["_izo_tool_runs"]] == ["web_search"]
    rejected = json.loads(requests[1]["messages"][-1]["content"])
    assert rejected["ok"] is False


def test_local_chat_forces_selected_image_intent_without_model_tool_call(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_ollama(*, body, timeout_seconds):
        captured["messages"] = body["messages"]
        return "Создаю изображение.", {"message": {"role": "assistant", "content": "Создаю изображение."}}

    monkeypatch.setattr(phone_chat, "request_ollama_chat_message", fake_ollama)
    request = PhoneChatRequest(
        messages=[{"role": "user", "content": "Красная кружка на белом фоне"}],
        toolChoice="generate_image",
    )

    reply, payload, _model = asyncio.run(phone_chat.phone_chat_ollama(request, _deps(), _config()))

    assert reply == "Создаю изображение."
    assert payload["_izo_tool_runs"] == [{
        "name": "generate_image", "ok": True, "status": "requested",
        "prompt": "Красная кружка на белом фоне", "aspectRatio": "1:1",
    }]
    messages = captured["messages"]
    assert any(item.get("role") == "user" and item.get("content") == "Красная кружка на белом фоне" for item in messages)
    assert messages[-1]["role"] == "tool"


def test_forced_image_uses_model_context_attachment_and_requested_ratio(monkeypatch) -> None:
    requests: list[dict[str, object]] = []

    async def fake_ollama(*, body, timeout_seconds):
        requests.append(json.loads(json.dumps(body)))
        if len(requests) == 1:
            assert any("обязательно вызови generate_image" in str(item.get("content") or "") for item in body["messages"])
            assert body["messages"][-1]["images"] == ["YQ=="]
            return "", {"message": {"role": "assistant", "content": "", "tool_calls": [{
                "function": {"name": "generate_image", "arguments": {
                    "prompt": "Красная кружка из приложенного референса на белом фоне",
                }},
            }]}}
        return "Создаю изображение.", {"message": {"role": "assistant", "content": "Создаю изображение."}}

    monkeypatch.setattr(phone_chat, "request_ollama_chat_message", fake_ollama)
    request = PhoneChatRequest(
        messages=[
            {"role": "user", "content": "Нужна красная кружка на белом фоне."},
            {"role": "assistant", "content": "Сделаем предметный кадр."},
            {"role": "user", "content": "Создай это горизонтально, 16:9."},
        ],
        images=["data:image/png;base64,YQ=="],
        toolChoice="generate_image",
    )

    reply, payload, _model = asyncio.run(phone_chat.phone_chat_ollama(request, _deps(), _config()))

    assert reply == "Создаю изображение."
    assert payload["_izo_tool_runs"] == [{
        "name": "generate_image", "ok": True, "status": "requested",
        "prompt": "Красная кружка из приложенного референса на белом фоне", "aspectRatio": "16:9",
    }]
    assert len(requests) == 2
    assert [item["function"]["name"] for item in requests[0]["tools"]] == ["generate_image"]
    assert "tools" not in requests[1]


def test_forced_image_fallback_preserves_conversation_and_latest_format(monkeypatch) -> None:
    calls = 0

    async def fake_ollama(*, body, timeout_seconds):
        nonlocal calls
        calls += 1
        content = "Я учёл предыдущую идею." if calls == 1 else "Создаю изображение."
        return content, {"message": {"role": "assistant", "content": content}}

    monkeypatch.setattr(phone_chat, "request_ollama_chat_message", fake_ollama)
    request = PhoneChatRequest(
        messages=[
            {"role": "user", "content": "Нарисуем маяк во время шторма."},
            {"role": "assistant", "content": "Добавим холодный кинематографичный свет."},
            {"role": "user", "content": "Сделай это горизонтально."},
        ],
        toolChoice="generate_image",
    )

    _reply, payload, _model = asyncio.run(phone_chat.phone_chat_ollama(request, _deps(), _config()))

    tool = payload["_izo_tool_runs"][0]
    assert tool["aspectRatio"] == "16:9"
    assert "маяк во время шторма" in tool["prompt"]
    assert "холодный кинематографичный свет" in tool["prompt"]
    assert "Сделай это горизонтально" in tool["prompt"]


def test_cloud_chat_serializes_forced_tool_result_with_openrouter_contract(monkeypatch) -> None:
    requests: list[dict[str, object]] = []

    async def fake_openrouter(*, base_url, headers, body, timeout_seconds):
        requests.append(json.loads(json.dumps(body)))
        if body.get("tools") and body["tools"][0]["type"] == "openrouter:web_search":
            return 200, {
                "choices": [{"message": {"content": "Найдено.", "annotations": []}}],
                "usage": {"cost": 0.02},
            }
        if len(requests) == 1:
            return 200, {
                "choices": [{"message": {"content": "", "tool_calls": [{
                    "id": "call_search_1",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": '{"query":"проверяемый факт"}'},
                }]}}],
                "usage": {"cost": 0.01},
            }
        return 200, {"choices": [{"message": {"content": "Факт проверен."}}], "usage": {"cost": 0.03}}

    monkeypatch.setattr(phone_chat, "request_openrouter_chat_completion", fake_openrouter)
    request = PhoneChatRequest(
        messages=[{"role": "user", "content": "Проверь этот факт"}],
        toolChoice="web_search",
    )

    reply, payload, _model = asyncio.run(phone_chat.phone_chat_openrouter(request, _deps(), _config()))

    assert reply == "Факт проверен."
    assert payload["_izo_tool_runs"][0]["name"] == "web_search"
    assistant_tool_call = requests[2]["messages"][-2]
    assert isinstance(assistant_tool_call["tool_calls"][0]["function"]["arguments"], str)
    assert requests[2]["messages"][-1]["tool_call_id"] == assistant_tool_call["tool_calls"][0]["id"]
    assert "tools" not in requests[2]
    assert [item["usage"]["cost"] for item in payload["_izo_tool_payloads"]] == [0.02, 0.01]
    assert phone_chat.extract_openrouter_generation_cost(payload) + sum(
        phone_chat.extract_openrouter_generation_cost(item) for item in payload["_izo_tool_payloads"]
    ) == pytest.approx(0.06)


def test_cloud_forced_image_rejects_hallucinated_search_tool(monkeypatch) -> None:
    requests: list[dict[str, object]] = []

    async def fake_openrouter(*, base_url, headers, body, timeout_seconds):
        requests.append(json.loads(json.dumps(body)))
        if len(requests) == 1:
            return 200, {"choices": [{"message": {"content": "", "tool_calls": [{
                "id": "call_wrong_search",
                "type": "function",
                "function": {"name": "web_search", "arguments": '{"query":"не запускать"}'},
            }]}}], "usage": {"cost": 0.01}}
        content = "Описание изображения." if len(requests) == 2 else "Создаю изображение."
        return 200, {"choices": [{"message": {"content": content}}], "usage": {"cost": 0.02}}

    async def fail_web_search(*args, **kwargs):
        raise AssertionError("unselected web search must not run")

    monkeypatch.setattr(phone_chat, "request_openrouter_chat_completion", fake_openrouter)
    monkeypatch.setattr(phone_chat, "_web_search", fail_web_search)
    request = PhoneChatRequest(
        messages=[{"role": "user", "content": "Создай изображение маяка"}],
        toolChoice="generate_image",
    )

    _reply, payload, _model = asyncio.run(phone_chat.phone_chat_openrouter(request, _deps(), _config()))

    assert [item["name"] for item in payload["_izo_tool_runs"]] == ["generate_image"]
    assert payload["_izo_tool_runs"][0]["prompt"] == "Создай изображение маяка"
    rejected = json.loads(requests[1]["messages"][-1]["content"])
    assert rejected["ok"] is False
    assert [item["usage"]["cost"] for item in payload["_izo_tool_payloads"]] == [0.01, 0.02]


def test_cloud_forced_image_fallback_keeps_context_ratio_and_tool_protocol(monkeypatch) -> None:
    requests: list[dict[str, object]] = []

    async def fake_openrouter(*, base_url, headers, body, timeout_seconds):
        requests.append(json.loads(json.dumps(body)))
        content = "Описание уточнено по истории." if len(requests) == 1 else "Создаю изображение."
        cost = 0.02 if len(requests) == 1 else 0.03
        return 200, {"choices": [{"message": {"content": content}}], "usage": {"cost": cost}}

    monkeypatch.setattr(phone_chat, "request_openrouter_chat_completion", fake_openrouter)
    request = PhoneChatRequest(
        messages=[
            {"role": "user", "content": "Сцена с маяком во время шторма."},
            {"role": "assistant", "content": "Сохраняем драматичный свет."},
            {"role": "user", "content": "Создай её вертикально."},
        ],
        toolChoice="generate_image",
    )

    _reply, payload, _model = asyncio.run(phone_chat.phone_chat_openrouter(request, _deps(), _config()))

    tool = payload["_izo_tool_runs"][0]
    assert tool["aspectRatio"] == "9:16"
    assert "маяком во время шторма" in tool["prompt"]
    assistant_tool_call = requests[1]["messages"][-2]
    assert isinstance(assistant_tool_call["tool_calls"][0]["function"]["arguments"], str)
    assert requests[1]["messages"][-1]["tool_call_id"] == assistant_tool_call["tool_calls"][0]["id"]
    assert "tools" not in requests[1]
    assert payload["usage"]["cost"] == 0.03
    assert [item["usage"]["cost"] for item in payload["_izo_tool_payloads"]] == [0.02]
    assert phone_chat.extract_openrouter_generation_cost(payload) + sum(
        phone_chat.extract_openrouter_generation_cost(item) for item in payload["_izo_tool_payloads"]
    ) == pytest.approx(0.05)


def test_cloud_tool_call_accumulates_every_main_round_cost(monkeypatch) -> None:
    calls = 0

    async def fake_openrouter(*, base_url, headers, body, timeout_seconds):
        nonlocal calls
        calls += 1
        if calls == 1:
            return 200, {
                "choices": [{"message": {"content": "", "tool_calls": [{
                    "id": "call_cost_1",
                    "function": {"name": "generate_image", "arguments": {"prompt": "маяк"}},
                }]}}],
                "usage": {"cost": 0.01},
            }
        return 200, {"choices": [{"message": {"content": "Создаю изображение."}}], "usage": {"cost": 0.02}}

    monkeypatch.setattr(phone_chat, "request_openrouter_chat_completion", fake_openrouter)

    _reply, payload, _model = asyncio.run(phone_chat.phone_chat_openrouter(
        PhoneChatRequest(messages=[{"role": "user", "content": "Создай маяк"}]),
        _deps(),
        _config(),
    ))

    assert payload["usage"]["cost"] == 0.02
    assert [item["usage"]["cost"] for item in payload["_izo_tool_payloads"]] == [0.01]
    assert phone_chat.extract_openrouter_generation_cost(payload) + sum(
        phone_chat.extract_openrouter_generation_cost(item) for item in payload["_izo_tool_payloads"]
    ) == pytest.approx(0.03)


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


def test_image_tool_internal_json_is_never_returned_to_user(monkeypatch) -> None:
    calls = 0

    async def fake_ollama(*, body, timeout_seconds):
        nonlocal calls
        calls += 1
        if calls == 1:
            return "", {"message": {"role": "assistant", "content": "", "tool_calls": [{
                "function": {"name": "generate_image", "arguments": {"prompt": "Москва осенью"}},
            }]}}
        envelope = '{"action":"generate_image","action_input":{"prompt":"Moscow in autumn"}}'
        return envelope, {"message": {"role": "assistant", "content": envelope}}

    monkeypatch.setattr(phone_chat, "request_ollama_chat_message", fake_ollama)
    reply, payload, _model = asyncio.run(phone_chat.phone_chat_ollama(
        PhoneChatRequest(messages=[{"role": "user", "content": "Создай картинку Москвы осенью"}]),
        _deps(),
        _config(),
    ))

    assert reply == "Создаю изображение."
    assert "action_input" not in reply
    assert payload["_izo_tool_runs"][0]["name"] == "generate_image"


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
