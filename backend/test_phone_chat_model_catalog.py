from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers.phone_chat import PhoneChatDependencies, create_phone_chat_router


def test_public_chat_catalog_uses_publication_and_canonical_economics() -> None:
    model_id = "provider/paid-model"

    async def text_models():
        return [{
            "id": model_id,
            "name": "Paid model",
            "inputPerMillionUsd": 1.0,
            "outputPerMillionUsd": 2.0,
            "contextLength": 128_000,
        }]

    config = {
        "chat": {
            "enabled": True,
            "localEnabled": True,
            "localLabel": "ИЗО Чат",
            "publishedApiModels": [model_id],
            "enabledApiModels": [model_id],
            "apiTierAccess": {"mini": [model_id]},
            "defaultModel": model_id,
            "usageBillingEnabled": True,
        }
    }
    deps = PhoneChatDependencies(
        require_trusted_user=lambda _request: {"legacy_user_id": "web-test"},
        assistant_models_config=lambda: config,
        openrouter_headers=lambda: {},
        record_openrouter_availability=lambda _status: None,
        record_event=lambda *args, **kwargs: None,
        openrouter_text_models=text_models,
        request_lifecycle=None,
        connect_db=None,
        usd_rub_snapshot=lambda: {"rate": 100.0, "fetchedAt": "2026-08-28T10:00:00+00:00"},
        openrouter_economy=lambda: {"usdFeePercent": 30.0, "minMarginPercent": 50.0, "tokenRub": 5.0},
    )
    app = FastAPI()
    app.include_router(create_phone_chat_router(deps))

    with TestClient(app) as client:
        response = client.get("/api/phone/chat/models")

    assert response.status_code == 200, response.text
    body = response.json()
    paid = next(item for item in body["models"] if item["id"] == model_id)
    assert paid["available"] is True
    assert paid["inputPerMillionProductTokens"] == 52.0
    assert paid["outputPerMillionProductTokens"] == 104.0
    assert paid["retailPerMillionProductTokens"] == 104.0
    assert paid["economics"]["schema"] == "text-model-economics-v1"
    assert paid["economics"]["millionRussianChars"]["input"]["reservedTokens"] == 13.0


def test_public_chat_catalog_never_exposes_hidden_model() -> None:
    hidden_id = "provider/hidden-model"

    async def text_models():
        return [{"id": hidden_id, "inputPerMillionUsd": 1.0, "outputPerMillionUsd": 2.0}]

    config = {
        "chat": {
            "enabled": True,
            "localEnabled": True,
            "publishedApiModels": [],
            "enabledApiModels": [hidden_id],
            "apiTierAccess": {"mini": [hidden_id]},
        }
    }
    deps = PhoneChatDependencies(
        require_trusted_user=lambda _request: {"legacy_user_id": "web-test"},
        assistant_models_config=lambda: config,
        openrouter_headers=lambda: {},
        record_openrouter_availability=lambda _status: None,
        record_event=lambda *args, **kwargs: None,
        openrouter_text_models=text_models,
        request_lifecycle=None,
        connect_db=None,
        usd_rub_snapshot=lambda: {"rate": 100.0},
        openrouter_economy=lambda: {"usdFeePercent": 30.0, "minMarginPercent": 50.0, "tokenRub": 5.0},
    )
    app = FastAPI()
    app.include_router(create_phone_chat_router(deps))

    with TestClient(app) as client:
        response = client.get("/api/phone/chat/models")

    assert response.status_code == 200
    assert hidden_id not in {item["id"] for item in response.json()["models"]}


def test_public_chat_catalog_marks_published_model_without_catalog_price_unavailable() -> None:
    model_id = "provider/temporarily-unpriced"

    async def empty_catalog():
        return []

    deps = PhoneChatDependencies(
        require_trusted_user=lambda _request: {"legacy_user_id": "web-test"},
        assistant_models_config=lambda: {"chat": {"enabled": True, "localEnabled": True, "publishedApiModels": [model_id], "enabledApiModels": [model_id], "apiTierAccess": {"mini": [model_id]}}},
        openrouter_headers=lambda: {}, record_openrouter_availability=lambda _status: None,
        record_event=lambda *args, **kwargs: None, openrouter_text_models=empty_catalog,
        request_lifecycle=None,
        connect_db=None, usd_rub_snapshot=lambda: {"rate": 100.0},
        openrouter_economy=lambda: {"usdFeePercent": 30.0, "minMarginPercent": 50.0, "tokenRub": 5.0},
    )
    app = FastAPI()
    app.include_router(create_phone_chat_router(deps))

    with TestClient(app) as client:
        response = client.get("/api/phone/chat/models")

    model = next(item for item in response.json()["models"] if item["id"] == model_id)
    assert model["available"] is False
    assert model["unavailableReason"] == "Нет проверенной цены модели"
    assert model["economics"]["priceStatus"] == "missing_catalog"
    assert model["economics"]["inputPerMillion"] is None
