from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main


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
        )
    assert response.status_code == 502
    assert "исходный пользовательский текст" not in response.text


def test_prompt_parser_accepts_strict_json_and_rejects_empty_value():
    assert main._parse_improved_prompt('{"improved_prompt":"готовый промпт"}') == "готовый промпт"
    object_content = {"choices": [{"message": {"content": {"improved_prompt": "ответ объектом"}}}]}
    assert main._parse_improved_prompt(main._openrouter_text_content(object_content)) == "ответ объектом"
    parsed_content = {"choices": [{"message": {"content": None, "parsed": {"improved_prompt": "parsed ответ"}}}]}
    assert main._parse_improved_prompt(main._openrouter_text_content(parsed_content)) == "parsed ответ"
    tool_content = {"choices": [{"message": {"content": None, "tool_calls": [{"function": {"arguments": '{"improved_prompt":"tool ответ"}'}}]}}]}
    assert main._parse_improved_prompt(main._openrouter_text_content(tool_content)) == "tool ответ"
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


def test_default_prompt_instructions_are_visible_in_russian(prompt_user):
    config = main.assistant_models_config()["improve"]
    message = main._improve_system_message(main.ImprovePromptRequest(prompt="дом", mode="text", language="ru"), config)
    assert "Ты улучшаешь" in message
    assert "Ответ верни на русском" in message
    assert "Составь подробный промпт" in message


def test_admin_assistant_catalog_contains_ollama_and_openrouter_prices(prompt_user, monkeypatch):
    with main.db() as conn:
        conn.execute("UPDATE users SET role = 'admin' WHERE internal_user_id = ?", (prompt_user["internal_user_id"],))

    async def fake_ollama():
        return {"ok": True, "baseUrl": "http://127.0.0.1:11434", "models": [{"name": "gemma4:31b-cloud"}]}

    async def fake_openrouter_models(force=False):
        return [{"id": "deepseek/deepseek-v4-flash", "name": "DeepSeek V4 Flash", "inputPerMillionUsd": 0.077, "outputPerMillionUsd": 0.154, "contextLength": 1048576}]

    monkeypatch.setattr(main, "ollama_models_status", fake_ollama)
    monkeypatch.setattr(main, "openrouter_text_models", fake_openrouter_models)
    with TestClient(main.app) as client:
        response = client.get("/api/admin/assistants", cookies={"onenode_session": prompt_user["cookie"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ollama"]["models"][0]["name"] == "gemma4:31b-cloud"
    assert body["openrouterModels"][0]["inputPerMillionUsd"] == 0.077


def test_voice_transcription_rejects_too_short_recording(prompt_user):
    with TestClient(main.app) as client:
        response = client.post(
            "/api/tools/transcribe?duration_ms=400&language=ru",
            files={"file": ("voice.webm", b"audio", "audio/webm")},
            cookies={"onenode_session": prompt_user["cookie"]},
        )
    assert response.status_code == 400
    assert "не меньше" in response.text


def test_voice_transcription_returns_provider_text(prompt_user, monkeypatch):
    captured = {}

    async def fake_transcribe(audio, audio_format, language, config=None):
        captured.update({"audio": audio, "format": audio_format, "language": language})
        return "девушка у вечернего окна", {"usage": {"cost": 0.0002}}

    monkeypatch.setattr(main, "transcribe_audio_openrouter", fake_transcribe)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/tools/transcribe?duration_ms=1400&language=ru",
            files={"file": ("voice.webm", b"not-real-audio", "audio/webm")},
            cookies={"onenode_session": prompt_user["cookie"]},
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
        )
    assert response.status_code == 200, response.text
    assert response.json()["provider"] == "local"
    assert response.json()["model"] == "gemma4:12b"
