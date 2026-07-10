from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "account_sync_models_tokens.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    main.init_db()
    return db_file


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def make_user(iuid: str, legacy: str, *, role: str = "user", plan: str = "mini", balance: int = 50) -> None:
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, internal_user_id, role, plan, token_balance, language, created_at, last_login_at) "
            "VALUES (?, ?, ?, ?, ?, 'ru', '2026-01-01', '2026-01-01')",
            (legacy, iuid, role, plan, balance),
        )


def test_user_tariffs_and_model_access_follow_admin_settings(temp_db):
    make_user("iuid-user", "web_user", plan="pro")
    token = main.create_auth_session("iuid-user", "web_user", provider="web_email", platform="web")["session_token"]
    tariffs = main.normalize_tariffs({
        **main.DEFAULT_TARIFFS,
        "pro": {
            **main.DEFAULT_TARIFFS["pro"],
            "title": "Creator Pro",
            "price_rub_month": 2222,
            "model_defaults": {
                "fast": "server:local_flux_klein",
                "standard": "black-forest-labs/flux.2-pro",
                "max": "black-forest-labs/flux.2-max",
            },
        },
    })
    openrouter = {
        "enabled": {
            "text_to_image": ["black-forest-labs/flux.2-pro", "black-forest-labs/flux.2-max"],
        },
        "access": {
            "text_to_image": {
                "pro": ["black-forest-labs/flux.2-pro", "black-forest-labs/flux.2-max"],
            },
        }
    }
    with main.db() as conn:
        conn.execute(
            "INSERT INTO admin_settings (key, value_json, updated_at) VALUES ('tariffs', ?, '2026-01-01')",
            (json.dumps(tariffs, ensure_ascii=False),),
        )
        conn.execute(
            "INSERT INTO admin_settings (key, value_json, updated_at) VALUES ('openrouter_models', ?, '2026-01-01')",
            (json.dumps(openrouter, ensure_ascii=False),),
        )

    with TestClient(main.app) as client:
        tariffs_response = client.get("/api/tariffs", headers=bearer(token))
        access_response = client.get("/api/model-access", headers=bearer(token))

    assert tariffs_response.status_code == 200
    assert tariffs_response.json()["tariffs"]["pro"]["title"] == "Creator Pro"
    assert tariffs_response.json()["tariffs"]["pro"]["price_rub_month"] == 2222
    text_mode = access_response.json()["modes"]["text_to_image"]
    assert text_mode["label"] == "По тексту"
    assert text_mode["presets"]["standard"] == "black-forest-labs/flux.2-pro"
    assert "black-forest-labs/flux.2-max" in [item["id"] for item in text_mode["models"]]


def test_account_token_history_counts_balance_and_included_usage(temp_db):
    make_user("iuid-user", "web_user", plan="pro", balance=25)
    token = main.create_auth_session("iuid-user", "web_user", provider="web_email", platform="web")["session_token"]
    now = datetime.now(timezone.utc).isoformat()
    with main.db() as conn:
        conn.execute(
            "INSERT INTO token_ledger (id, user_id, delta, reason, meta_json, created_at) VALUES "
            "('l1', 'web_user', 0, 'daily_generation', ?, ?),"
            "('l2', 'web_user', 0, 'openrouter_monthly_generation', ?, ?),"
            "('l3', 'web_user', -2, 'generation', ?, ?)",
            (
                json.dumps({"jobId": "job_daily", "provider": "comfyui", "mode": "text_to_image", "token_cost": 1}),
                now,
                json.dumps({"jobId": "job_or", "provider": "openrouter", "mode": "text_to_image", "token_cost": 3, "billing": {"modelName": "FLUX.2 Pro", "estimatedCostRub": 3.5}}),
                now,
                json.dumps({"jobId": "job_paid", "provider": "openrouter", "mode": "text_to_image", "token_cost": 2}),
                now,
            ),
        )

    with TestClient(main.app) as client:
        response = client.get("/api/account/token-history-v2?days=365", headers=bearer(token))

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["summary"]["spentTokens"] == 6
    assert data["summary"]["includedSpentTokens"] == 4
    assert data["summary"]["balanceSpentTokens"] == 2
    assert any(item["jobId"] == main.short_public_id("job_paid") and item["spentTokens"] == 2 for item in data["items"])
    assert any(item["source"] == "премиум-пакет" and item["model"] == "FLUX.2 Pro" for item in data["items"])
