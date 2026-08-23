from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from app.api.routers import phone_chat as phone_chat_router
# Browser-faithful contract: cookie-auth mutations carry an allowlisted Origin
# to pass the CSRF boundary (AUTH-LEGACY-001B). GET requests stay untouched.
from test_support.browser_origin import BROWSER_ORIGIN


@pytest.fixture
def prompt_user(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "prompt-improve.sqlite3")
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    main.init_db()
    internal_user_id = "iuid-prompt-improve"
    legacy_user_id = "web_prompt_improve"
    now = "2026-07-11T00:00:00+00:00"
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, internal_user_id, language, role, token_balance, created_at, last_login_at) "
            "VALUES (?, ?, 'ru', 'user', 100, ?, ?)",
            (legacy_user_id, internal_user_id, now, now),
        )
        conn.execute(
            "INSERT INTO auth_identities (id, internal_user_id, legacy_user_id, provider, provider_user_id, linked_at) "
            "VALUES ('identity-prompt', ?, ?, 'web_email', 'prompt@example.test', ?)",
            (internal_user_id, legacy_user_id, now),
        )
    session = main.create_auth_session(internal_user_id, legacy_user_id, provider="web_email", platform="web_desktop")
    return {"cookie": session["session_token"], "internal_user_id": internal_user_id}


def test_prompt_improvement_requires_trusted_session(prompt_user):
    with TestClient(main.app) as client:
        response = client.post("/api/tools/improve-prompt", json={"prompt": "красная машина", "mode": "text"})
    assert response.status_code == 401


def test_prompt_improvement_replaces_text_and_records_sanitized_usage(prompt_user, monkeypatch):
    captured = {}

    async def fake_improve(req, force_provider=None):
        captured["request"] = req
        return (
            "Красный спортивный автомобиль на городской улице, мягкий вечерний свет.",
            {"usage": {"prompt_tokens": 80, "completion_tokens": 22, "cost": 0.00001}},
            "api",
            "deepseek/deepseek-v4-flash",
        )

    monkeypatch.setattr(main, "improve_prompt_routed", fake_improve)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/tools/improve-prompt",
            json={"prompt": "красная машина", "mode": "text", "language": "ru"},
            cookies={"onenode_session": prompt_user["cookie"]},
            headers=BROWSER_ORIGIN,
        )

    assert response.status_code == 200, response.text
    assert response.json()["improvedPrompt"].startswith("Красный спортивный")
    assert captured["request"].prompt == "красная машина"
    with main.db() as conn:
        event = conn.execute(
            "SELECT properties_json FROM event_logs WHERE event_name = 'prompt_improved' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert event is not None
    assert "красная машина" not in event["properties_json"]


def test_prompt_improvement_provider_error_does_not_echo_or_replace_prompt(prompt_user, monkeypatch):
    async def failed_improve(_req, force_provider=None):
        raise RuntimeError("OpenRouter временно недоступен")

    monkeypatch.setattr(main, "improve_prompt_routed", failed_improve)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/tools/improve-prompt",
            json={"prompt": "исходный пользовательский текст", "mode": "i2i"},
            cookies={"onenode_session": prompt_user["cookie"]},
            headers=BROWSER_ORIGIN,
        )
    assert response.status_code == 502
    assert "исходный пользовательский текст" not in response.text


def test_local_route_never_falls_back_to_openrouter(monkeypatch):
    monkeypatch.setattr(main, "assistant_models_config", lambda: {"improve": {**main.DEFAULT_ASSISTANT_MODELS_CONFIG["improve"], "route": "local"}})
    calls: list[str] = []

    async def resident(_config):
        calls.append("resident")

    async def local(_req, _config):
        calls.append("local")
        raise RuntimeError("local failed")

    async def api(_req, _config):
        calls.append("api")
        return "unexpected", {}

    monkeypatch.setattr(main, "ensure_configured_ollama_resident", resident)
    monkeypatch.setattr(main, "improve_prompt_ollama", local)
    monkeypatch.setattr(main, "improve_prompt_openrouter", api)
    with pytest.raises(main.PromptRouteError) as failure:
        asyncio.run(main.improve_prompt_routed(main.ImprovePromptRequest(prompt="дом")))
    assert calls == ["resident", "local"]
    assert failure.value.routing["requestedRoute"] == "local"


def test_api_route_never_calls_ollama(monkeypatch):
    config = {**main.DEFAULT_ASSISTANT_MODELS_CONFIG["improve"], "route": "api"}
    monkeypatch.setattr(main, "assistant_models_config", lambda: {"improve": config})

    async def local(*_args, **_kwargs):
        raise AssertionError("Ollama must not run")

    async def api(_req, _config):
        return "API результат", {"usage": {"cost": 0.1}}

    monkeypatch.setattr(main, "improve_prompt_ollama", local)
    monkeypatch.setattr(main, "improve_prompt_openrouter", api)
    improved, payload, provider, _model = asyncio.run(main.improve_prompt_routed(main.ImprovePromptRequest(prompt="дом")))
    assert improved == "API результат"
    assert provider == "api"
    assert payload["_izoRouting"]["attempts"][0]["provider"] == "api"


def test_auto_route_records_local_failure_and_api_fallback(monkeypatch):
    config = {**main.DEFAULT_ASSISTANT_MODELS_CONFIG["improve"], "route": "auto"}
    monkeypatch.setattr(main, "assistant_models_config", lambda: {"improve": config})

    async def resident(_config):
        raise RuntimeError("cold load failed")

    async def api(_req, _config):
        return "Резервный результат", {"usage": {"cost": 0.1}}

    monkeypatch.setattr(main, "ensure_configured_ollama_resident", resident)
    monkeypatch.setattr(main, "improve_prompt_openrouter", api)
    improved, payload, provider, _model = asyncio.run(main.improve_prompt_routed(main.ImprovePromptRequest(prompt="дом")))
    routing = payload["_izoRouting"]
    assert improved == "Резервный результат"
    assert provider == "api"
    assert routing["fallbackUsed"] is True
    assert [attempt["provider"] for attempt in routing["attempts"]] == ["local", "api"]
    assert routing["attempts"][0]["errorType"] == "RuntimeError"


def test_phone_chat_requires_trusted_session():
    with TestClient(main.app) as client:
        response = client.post("/api/phone/chat", json={"messages": [{"role": "user", "content": "Привет"}]})
    assert response.status_code == 401


def test_phone_chat_returns_real_provider_answer_without_logging_message(prompt_user, monkeypatch):
    captured = {}

    async def fake_chat(req):
        captured["request"] = req
        return "Готов помочь с идеей изображения.", {"usage": {"prompt_tokens": 8}}, "local", "gemma4:31b-cloud"

    async def routed(req, _deps):
        return await fake_chat(req)

    monkeypatch.setattr(phone_chat_router, "route_phone_chat", routed)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/phone/chat",
            json={"messages": [{"role": "user", "content": "Секретная идея пользователя"}], "route": "auto"},
            cookies={"onenode_session": prompt_user["cookie"]},
            headers=BROWSER_ORIGIN,
        )

    assert response.status_code == 200, response.text
    assert response.json()["reply"] == "Готов помочь с идеей изображения."
    assert captured["request"].messages[-1].content == "Секретная идея пользователя"
    with main.db() as conn:
        event = conn.execute(
            "SELECT properties_json FROM event_logs WHERE event_name = 'phone_chat_answered' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert event is not None
    assert "Секретная идея пользователя" not in event["properties_json"]


def test_phone_chat_provider_failure_is_neutral(prompt_user, monkeypatch):
    async def failed_chat(_req):
        raise RuntimeError("provider balance and private diagnostic")

    async def routed(req, _deps):
        return await failed_chat(req)

    monkeypatch.setattr(phone_chat_router, "route_phone_chat", routed)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/phone/chat",
            json={"messages": [{"role": "user", "content": "Ответь"}]},
            cookies={"onenode_session": prompt_user["cookie"]},
            headers=BROWSER_ORIGIN,
        )
    assert response.status_code == 502
    assert "provider balance" not in response.text
    assert "Чат временно недоступен" in response.text


def test_phone_chat_rejects_non_image_attachment(prompt_user, monkeypatch):
    async def should_not_run(_req):
        raise AssertionError("provider must not receive an invalid attachment")

    async def routed(req, _deps):
        return await should_not_run(req)

    monkeypatch.setattr(phone_chat_router, "route_phone_chat", routed)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/phone/chat",
            json={
                "messages": [{"role": "user", "content": "Что на картинке?"}],
                "images": ["data:text/plain;base64,dGVzdA=="],
            },
            cookies={"onenode_session": prompt_user["cookie"]},
            headers=BROWSER_ORIGIN,
        )
    assert response.status_code == 400
    assert "JPEG" in response.text


def test_prompt_parser_accepts_strict_json_and_rejects_empty_value():
    assert main._parse_improved_prompt('{"improved_prompt":"готовый промпт"}') == "готовый промпт"
    object_content = {"choices": [{"message": {"content": {"improved_prompt": "ответ объектом"}}}]}
    assert main._parse_improved_prompt(main._openrouter_text_content(object_content)) == "ответ объектом"
    parsed_content = {"choices": [{"message": {"content": None, "parsed": {"improved_prompt": "parsed ответ"}}}]}
    assert main._parse_improved_prompt(main._openrouter_text_content(parsed_content)) == "parsed ответ"
    tool_content = {"choices": [{"message": {"content": None, "tool_calls": [{"function": {"arguments": '{"improved_prompt":"tool ответ"}'}}]}}]}
    assert main._parse_improved_prompt(main._openrouter_text_content(tool_content)) == "tool ответ"
    reasoning_content = {"choices": [{"message": {"content": None, "reasoning": '{"improved_prompt":"reasoning ответ"}'}}]}
    assert main._parse_improved_prompt(main._openrouter_text_content(reasoning_content)) == "reasoning ответ"
    reasoning_details = {"choices": [{"message": {"content": None, "reasoning_details": [{"text": '{"improved_prompt":"details ответ"}'}]}}]}
    assert main._parse_improved_prompt(main._openrouter_text_content(reasoning_details)) == "details ответ"
    with pytest.raises(RuntimeError):
        main._parse_improved_prompt('{"improved_prompt":""}')


def test_assistant_config_merges_saved_values_with_mode_defaults(prompt_user):
    with main.db() as conn:
        conn.execute(
            "INSERT INTO admin_settings (key, value_json, updated_at) VALUES ('assistant_models', ?, '2026-07-11T00:00:00+00:00')",
            ('{"improve":{"route":"local","localModel":"gemma4:12b","modePrompts":{"text":"custom text rule"}}}',),
        )
    config = main.assistant_models_config()
    assert config["improve"]["route"] == "local"
    assert config["improve"]["modePrompts"]["text"] == "custom text rule"
    assert config["improve"]["modePrompts"]["mask"]


def test_assistant_config_migrates_fake_qwen_ollama_tag(prompt_user):
    with main.db() as conn:
        conn.execute(
            "INSERT INTO admin_settings (key, value_json, updated_at) VALUES ('assistant_models', ?, '2026-07-15T00:00:00+00:00')",
            ('{"voice":{"route":"qwen","localModel":"qwen3-asr:1.7b"}}',),
        )
    voice = main.assistant_models_config()["voice"]
    assert voice["route"] == "qwen"
    assert voice["localModel"] == "gemma4:12b"
    assert voice["qwenModel"] == "Qwen/Qwen3-ASR-1.7B"
    assert voice["qwenBaseUrl"] == "http://127.0.0.1:8001"


def test_default_prompt_instructions_are_visible_in_russian(prompt_user):
    config = main.assistant_models_config()["improve"]
    message = main._improve_system_message(main.ImprovePromptRequest(prompt="дом", mode="text", language="ru"), config)
    assert "Ты улучшаешь" in message
    assert "Ответ верни на русском" in message
    assert "Составь подробный промпт" in message


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("text_to_video", "цельный промпт для видео"),
        ("image_to_video", "движение исходного кадра"),
        ("first_last_frame", "переход между начальным и конечным"),
        ("reference_to_video", "загруженным референсам"),
    ],
)
def test_video_prompt_improvement_modes_have_specific_rules(prompt_user, mode, expected):
    config = main.assistant_models_config()["improve"]
    request = main.ImprovePromptRequest(prompt="тестовая сцена", mode=mode, language="ru")
    message = main._improve_system_message(request, config)
    assert expected in message


def test_admin_assistant_catalog_contains_ollama_and_openrouter_prices(prompt_user, monkeypatch):
    with main.db() as conn:
        conn.execute("UPDATE users SET role = 'admin' WHERE internal_user_id = ?", (prompt_user["internal_user_id"],))

    async def fake_ollama():
        return {"ok": True, "baseUrl": "http://127.0.0.1:11434", "models": [{"name": "gemma4:31b-cloud"}]}

    async def fake_openrouter_models(force=False):
        return [{"id": "deepseek/deepseek-v4-flash", "name": "DeepSeek V4 Flash", "inputPerMillionUsd": 0.077, "outputPerMillionUsd": 0.154, "contextLength": 1048576}]

    async def fake_openrouter_audio_models(force=False):
        return [{"id": "google/gemini-audio", "name": "Gemini Audio", "inputPerMillionUsd": 0.1, "outputPerMillionUsd": 0.4, "contextLength": 1048576}]

    async def fake_qwen(_config=None):
        return {"ok": False, "baseUrl": "http://127.0.0.1:8001", "models": [], "error": "ConnectError"}

    monkeypatch.setattr(main, "ollama_models_status", fake_ollama)
    monkeypatch.setattr(main, "qwen_asr_status", fake_qwen)
    monkeypatch.setattr(main, "openrouter_text_models", fake_openrouter_models)
    monkeypatch.setattr(main, "openrouter_audio_models", fake_openrouter_audio_models)
    with TestClient(main.app) as client:
        response = client.get("/api/admin/assistants", cookies={"onenode_session": prompt_user["cookie"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ollama"]["models"][0]["name"] == "gemma4:31b-cloud"
    assert body["qwen"]["ok"] is False
    assert body["openrouterModels"][0]["inputPerMillionUsd"] == 0.077
    assert body["openrouterAudioModels"][0]["id"] == "google/gemini-audio"


def test_admin_voice_test_uses_unsaved_selected_route(prompt_user, monkeypatch):
    with main.db() as conn:
        conn.execute("UPDATE users SET role = 'admin' WHERE internal_user_id = ?", (prompt_user["internal_user_id"],))

    captured = {}

    async def fake_routed(audio, audio_format, language, config=None, force_provider=None):
        captured.update({"audio": audio, "format": audio_format, "language": language, "provider": force_provider})
        return "точная проверка", {"usage": {}}, "api", "google/gemini-audio"

    monkeypatch.setattr(main, "transcribe_audio_routed", fake_routed)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/admin/assistants/voice-test?provider=auto&language=ru",
            files={"file": ("voice.wav", b"test-wav", "audio/wav")},
            cookies={"onenode_session": prompt_user["cookie"]},
            headers=BROWSER_ORIGIN,
        )

    assert response.status_code == 200, response.text
    assert response.json()["text"] == "точная проверка"
    assert captured == {"audio": b"test-wav", "format": "wav", "language": "русском", "provider": "auto"}


def test_voice_transcription_rejects_too_short_recording(prompt_user):
    with TestClient(main.app) as client:
        response = client.post(
            "/api/tools/transcribe?duration_ms=400&language=ru",
            files={"file": ("voice.webm", b"audio", "audio/webm")},
            cookies={"onenode_session": prompt_user["cookie"]},
            headers=BROWSER_ORIGIN,
        )
    assert response.status_code == 400
    assert "не меньше" in response.text


def test_voice_transcription_returns_provider_text(prompt_user, monkeypatch):
    captured = {}
    with main.db() as conn:
        conn.execute(
            "INSERT INTO admin_settings (key, value_json, updated_at) VALUES ('assistant_models', ?, '2026-07-12T00:00:00+00:00')",
            ('{"voice":{"route":"api","minRecordingSeconds":1}}',),
        )

    async def fake_transcribe(audio, audio_format, language, config=None):
        captured.update({"audio": audio, "format": audio_format, "language": language})
        return "девушка у вечернего окна", {"usage": {"cost": 0.0002}}

    monkeypatch.setattr(main, "transcribe_audio_openrouter", fake_transcribe)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/tools/transcribe?duration_ms=1400&language=ru",
            files={"file": ("voice.webm", b"not-real-audio", "audio/webm")},
            cookies={"onenode_session": prompt_user["cookie"]},
            headers=BROWSER_ORIGIN,
        )
    assert response.status_code == 200, response.text
    assert response.json()["text"] == "девушка у вечернего окна"
    assert captured == {"audio": b"not-real-audio", "format": "webm", "language": "русском"}


def test_voice_transcription_uses_local_ollama_route(prompt_user, monkeypatch):
    with main.db() as conn:
        conn.execute(
            "INSERT INTO admin_settings (key, value_json, updated_at) VALUES ('assistant_models', ?, '2026-07-12T00:00:00+00:00')",
            ('{"voice":{"route":"local","localModel":"gemma4:12b","minRecordingSeconds":1}}',),
        )

    async def fake_local(audio, audio_format, language, config=None):
        assert config["localModel"] == "gemma4:12b"
        return "локальная расшифровка", {"message": {"content": "локальная расшифровка"}}

    monkeypatch.setattr(main, "transcribe_audio_ollama", fake_local)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/tools/transcribe?duration_ms=1600&language=ru",
            files={"file": ("voice.webm", b"not-real-audio", "audio/webm")},
            cookies={"onenode_session": prompt_user["cookie"]},
            headers=BROWSER_ORIGIN,
        )
    assert response.status_code == 200, response.text
    assert response.json()["provider"] == "local"
    assert response.json()["model"] == "gemma4:12b"


def test_voice_transcription_uses_qwen_service_route(prompt_user, monkeypatch):
    with main.db() as conn:
        conn.execute(
            "INSERT INTO admin_settings (key, value_json, updated_at) VALUES ('assistant_models', ?, '2026-07-15T00:00:00+00:00')",
            ('{"voice":{"route":"qwen","qwenModel":"Qwen/Qwen3-ASR-1.7B","minRecordingSeconds":1}}',),
        )

    async def fake_qwen(audio, audio_format, language, config=None):
        assert audio == b"not-real-audio"
        assert config["qwenModel"] == "Qwen/Qwen3-ASR-1.7B"
        return "Qwen расшифровка", {"usage": {}}

    monkeypatch.setattr(main, "transcribe_audio_qwen", fake_qwen)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/tools/transcribe?duration_ms=1600&language=ru",
            files={"file": ("voice.webm", b"not-real-audio", "audio/webm")},
            cookies={"onenode_session": prompt_user["cookie"]},
            headers=BROWSER_ORIGIN,
        )
    assert response.status_code == 200, response.text
    assert response.json()["provider"] == "qwen"
    assert response.json()["text"] == "Qwen расшифровка"
