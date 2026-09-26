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
    monkeypatch.setattr(main, "worker_started", True)
    main.jobs.clear()
    main.init_db()
    now = datetime.now(timezone.utc)
    main._save_setting("exchange_usd_rub", {"rate": 80.0, "currency": "USD", "base": "RUB", "source": "test-fixture", "sourceUrl": "test://exchange", "sourceDate": now.date().isoformat(), "fetchedAt": now.isoformat(), "fetched_date": now.date().isoformat(), "fallback": False})
    async def fake_capabilities(*_args, **_kwargs):
        return [
            {"id": "black-forest-labs/flux.2-pro", "modes": ["text_to_image"], "supportedResolutionIds": ["sq-hd"], "maxInputReferences": 2},
            {"id": "black-forest-labs/flux.2-max", "modes": ["text_to_image"], "supportedResolutionIds": ["sq-hd"], "maxInputReferences": 2},
        ]
    monkeypatch.setattr(main, "fetch_openrouter_image_capabilities", fake_capabilities)
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
            "INSERT INTO admin_settings (key, value_json, updated_at) VALUES ('tariffs', ?, '2026-01-01') "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",
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
    local_model = next(item for item in text_mode["models"] if item["id"] == "server:local_flux_klein")
    api_model = next(item for item in text_mode["models"] if item["id"] == "black-forest-labs/flux.2-pro")
    assert local_model["generation"] == {"fixedSteps": 4, "allowsExactRepeat": False, "supportsSeed": True, "maxInputReferences": 4}
    assert api_model["generation"]["fixedSteps"] is None
    assert api_model["generation"]["allowsExactRepeat"] is True
    assert api_model["generation"]["supportsSeed"] is False
    assert api_model["generation"]["maxInputReferences"] >= 1


def test_job_status_restores_completed_result_from_database(temp_db):
    make_user("iuid-user", "web_user", plan="pro")
    token = main.create_auth_session("iuid-user", "web_user", provider="web_email", platform="web")["session_token"]
    now = datetime.now(timezone.utc).isoformat()
    settings = {"modelProfile": "openai/gpt-image-2", "tokenCost": 1, "generationTimeMs": 1234}
    with main.db() as conn:
        conn.execute(
            "INSERT INTO jobs (id, user_id, mode, provider, status, progress, prompt_original, prompt_translated, result_image_id, error_message, settings_json, created_at, started_at, completed_at) "
            "VALUES ('job_db_result', 'web_user', 'text_to_image', 'openrouter', 'completed', 100, 'test prompt', '', 'img_db_result', NULL, ?, ?, ?, ?)",
            (json.dumps(settings, ensure_ascii=False), now, now, now),
        )
        conn.execute(
            "INSERT INTO images (id, user_id, job_id, url, thumbnail_url, width, height, mode, provider, prompt_original, prompt_translated, settings_json, is_favorite, created_at) "
            "VALUES ('img_db_result', 'web_user', 'job_db_result', '/api/media/web_user/result.png', '/api/media/web_user/thumb.png', 1024, 1024, 'text_to_image', 'openrouter', 'test prompt', '', ?, 0, ?)",
            (json.dumps(settings, ensure_ascii=False), now),
        )
    main.jobs.clear()

    with TestClient(main.app) as client:
        response = client.get("/api/jobs/job_db_result", headers=bearer(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["resultImageId"] == "img_db_result"
    assert body["resultUrl"] == "/api/media/web_user/result.png"
    assert body["tokenCost"] == 1


def test_openrouter_provider_size_plan_avoids_known_rejections(temp_db):
    openai_plan = main.openrouter_image_request_plan("openai/gpt-image-1-mini", 1280, 720)
    recraft_plan = main.openrouter_image_request_plan("recraft/recraft-v4.1", 1280, 720)
    sourceful_plan = main.openrouter_image_request_plan("sourceful/riverflow-v2.5-fast", 1280, 720)
    seed_plan = main.openrouter_image_request_plan("bytedance-seed/seedream-4.5", 1280, 720)
    google_plan = main.openrouter_image_request_plan("google/gemini-3.1-flash-lite-image", 1280, 720)

    assert openai_plan["size"] == "1536x1024"
    assert recraft_plan["size"] == "1536x1024"
    assert sourceful_plan["size"] == "16:9"
    assert seed_plan["size"] == "1280x720"
    assert seed_plan["strategy"] == "requested_size"
    assert int(seed_plan["billing_width"]) * int(seed_plan["billing_height"]) == 921_600
    assert google_plan["aspect_ratio"] == "16:9"
    assert google_plan["resolution"] == "1K"


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
    # Historical zero-delta package rows stay in the included subtotal. New
    # generations use only the two-account contract and never create them.
    assert data["summary"]["includedSpentTokens"] == 4
    assert data["summary"]["balanceSpentTokens"] == 2
    assert any(item["jobId"] == main.short_public_id("job_paid") and item["spentTokens"] == 2 for item in data["items"])
    assert any(item["source"] == "основной баланс" and item["model"] == "FLUX.2 Pro" for item in data["items"])


def test_openrouter_generation_rejects_model_not_enabled_for_tariff(temp_db, monkeypatch):
    make_user("iuid-user", "web_user", plan="pro", balance=25)
    token = main.create_auth_session("iuid-user", "web_user", provider="web_email", platform="web")["session_token"]
    with main.db() as conn:
        conn.execute(
            "INSERT INTO admin_settings (key, value_json, updated_at) VALUES ('openrouter_models', ?, '2026-01-01')",
            (json.dumps({
                "enabled": {"text_to_image": ["black-forest-labs/flux.2-pro"]},
                "access": {"text_to_image": {"pro": ["black-forest-labs/flux.2-pro"]}},
            }, ensure_ascii=False),),
        )

    async def fake_billing(_req):
        return {"chargedTokens": 3, "modelName": "FLUX.2 Max", "estimatedCostRub": 7.0}

    monkeypatch.setattr(main, "estimate_openrouter_billing", fake_billing)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/generate",
            headers=bearer(token),
            json={
                "mode": "text_to_image",
                "provider": "openrouter",
                "prompt": "test",
                "modelProfile": "black-forest-labs/flux.2-max",
                "width": 1024,
                "height": 1024,
                "steps": 4,
            },
        )

    assert response.status_code == 403
    with main.db() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM token_ledger").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()["c"] == 0


def test_openrouter_generation_uses_main_balance_only(temp_db, monkeypatch):
    make_user("iuid-user", "web_user", plan="pro", balance=25)
    token = main.create_auth_session("iuid-user", "web_user", provider="web_email", platform="web")["session_token"]
    tariffs = main.normalize_tariffs({
        **main.DEFAULT_TARIFFS,
        "pro": {**main.DEFAULT_TARIFFS["pro"], "monthly_tokens": 5},
    })
    with main.db() as conn:
        conn.execute(
            "INSERT INTO admin_settings (key, value_json, updated_at) VALUES ('tariffs', ?, '2026-01-01') "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",
            (json.dumps(tariffs, ensure_ascii=False),),
        )
        conn.execute(
            "INSERT INTO admin_settings (key, value_json, updated_at) VALUES ('openrouter_models', ?, '2026-01-01')",
            (json.dumps({
                "enabled": {"text_to_image": ["black-forest-labs/flux.2-pro"]},
                "access": {"text_to_image": {"pro": ["black-forest-labs/flux.2-pro"]}},
            }, ensure_ascii=False),),
        )

    async def fake_billing(_req, _capability=None):
        return {"chargedTokens": 3, "modelName": "FLUX.2 Pro", "estimatedCostRub": 3.5}

    async def flux_pro_capabilities(*_args, **_kwargs):
        return [{
            "id": "black-forest-labs/flux.2-pro",
            "modes": ["text_to_image"],
            "supportedResolutionIds": ["sq-hd"],
        }]

    monkeypatch.setattr(main, "estimate_openrouter_billing", fake_billing)
    monkeypatch.setattr(main, "fetch_openrouter_image_capabilities", flux_pro_capabilities)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/generate",
            headers=bearer(token),
            json={
                "mode": "text_to_image",
                "provider": "openrouter",
                "prompt": "test",
                "modelProfile": "black-forest-labs/flux.2-pro",
                "width": 1024,
                "height": 1024,
                "steps": 4,
            },
        )
        history = client.get("/api/account/token-history-v2?days=365", headers=bearer(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tokenCost"] == 3
    assert body["tokenBalance"] == 22
    assert body["mainBalanceTokens"] == 22
    assert body["dailyTokenPart"] == 0
    assert body["mainBalanceTokenPart"] == 3
    assert history.status_code == 200
    assert history.json()["summary"]["includedSpentTokens"] == 0
    assert history.json()["summary"]["balanceSpentTokens"] == 3
    with main.db() as conn:
        user = conn.execute("SELECT token_balance, openrouter_monthly_tokens_used FROM users WHERE id = 'web_user'").fetchone()
        ledger = conn.execute("SELECT delta, reason, meta_json FROM token_ledger").fetchone()
    assert int(user["token_balance"]) == 22
    assert int(user["openrouter_monthly_tokens_used"]) == 0
    assert int(ledger["delta"]) == -3
    assert ledger["reason"] == "generation"
    assert json.loads(ledger["meta_json"])["token_cost"] == 3


def test_openrouter_non_text_mode_requires_live_model_capability_before_billing(temp_db, monkeypatch):
    make_user("iuid-user", "web_user", plan="pro", balance=25)
    token = main.create_auth_session("iuid-user", "web_user", provider="web_email", platform="web")["session_token"]
    with main.db() as conn:
        conn.execute(
            "INSERT INTO admin_settings (key, value_json, updated_at) VALUES ('openrouter_models', ?, '2026-01-01')",
            (json.dumps({
                "enabled": {"image_to_image": ["black-forest-labs/flux.2-pro"]},
                "access": {"image_to_image": {"pro": ["black-forest-labs/flux.2-pro"]}},
            }, ensure_ascii=False),),
        )

    async def fake_billing(_req):
        raise AssertionError("billing must not run for a capability-rejected OpenRouter mode")

    async def text_only_capabilities(*_args, **_kwargs):
        return [{
            "id": "black-forest-labs/flux.2-pro",
            "modes": ["text_to_image"],
            "supportedResolutionIds": ["sq-hd"],
        }]

    monkeypatch.setattr(main, "estimate_openrouter_billing", fake_billing)
    monkeypatch.setattr(main, "fetch_openrouter_image_capabilities", text_only_capabilities)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/generate",
            headers=bearer(token),
            json={
                "mode": "image_to_image",
                "provider": "openrouter",
                "prompt": "test",
                "modelProfile": "black-forest-labs/flux.2-pro",
                "inputImage1": "data:image/png;base64,iVBORw0KGgo=",
                "width": 1024,
                "height": 1024,
                "steps": 4,
            },
        )

    assert response.status_code == 400
    with main.db() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM token_ledger").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()["c"] == 0
