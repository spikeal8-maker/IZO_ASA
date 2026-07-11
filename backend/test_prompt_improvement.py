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

    async def fake_improve(req, _config=None):
        captured["request"] = req
        return "Красный спортивный автомобиль на городской улице, мягкий вечерний свет.", {
            "usage": {"prompt_tokens": 80, "completion_tokens": 22, "cost": 0.00001}
        }

    monkeypatch.setattr(main, "improve_prompt_openrouter", fake_improve)
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
    async def failed_improve(_req, _config=None):
        raise RuntimeError("OpenRouter временно недоступен")

    monkeypatch.setattr(main, "improve_prompt_openrouter", failed_improve)
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
