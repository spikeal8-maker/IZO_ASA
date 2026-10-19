"""Real video config route remains truthful when its optional catalog is offline."""
from __future__ import annotations

import asyncio
from contextlib import closing

import httpx
import pytest

import main
from app.integrations.openrouter import fetch_openrouter_video_models
from app.services import video_presentation
from test_video_generation_api import MODEL, video_api


REAL_CATALOG_LOADER = main.fetch_openrouter_video_catalog
PRIVATE_DIAGNOSTIC = "owned transport diagnostic must stay private"


@pytest.fixture
def config_api(video_api, monkeypatch):
    monkeypatch.setattr(main, "LOCAL_LTX_ENABLED", False)
    monkeypatch.setattr(main, "_openrouter_video_catalog_cache", {"ts": 0.0, "models": []})
    try:
        yield video_api
    finally:
        video_api.close()


def failing_catalog(monkeypatch, failure="connect"):
    requests = []

    def handler(request):
        requests.append(request)
        if failure == "connect":
            raise httpx.ConnectError(PRIVATE_DIAGNOSTIC, request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout(PRIVATE_DIAGNOSTIC, request=request)
        return httpx.Response(503 if failure == "http_503" else 200, text=PRIVATE_DIAGNOSTIC)

    async def models(**kwargs):
        return await fetch_openrouter_video_models(**kwargs, transport=httpx.MockTransport(handler))

    async def exchange():
        raise AssertionError("Offline catalog must not wait on the optional exchange refresh")

    monkeypatch.setattr(main, "fetch_openrouter_video_models", models)
    monkeypatch.setattr(main, "fetch_openrouter_video_catalog", REAL_CATALOG_LOADER)
    monkeypatch.setattr(main, "fetch_usd_rub_rate", exchange)
    return requests


@pytest.mark.parametrize("failure", ("connect", "timeout", "http_503", "invalid_json"))
def test_transport_failure_returns_unavailable_config_without_financial_writes(config_api, monkeypatch, failure):
    requests = failing_catalog(monkeypatch, failure)
    with closing(main.db()) as conn:
        before = [conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                  for table in ("jobs", "token_ledger", "images")]

    response = config_api.get("/api/video/config")

    assert response.status_code == 200
    value = response.json()
    assert value["catalog"] == {"status": "unavailable", "reasonCode": "VIDEO_CATALOG_UNAVAILABLE"}
    assert len(requests) == 1
    assert all(models == [] for models in value["modes"].values())
    assert all(row == {"enabled": 0, "tariff": 0, "reason": video_presentation.CATALOG_UNAVAILABLE_REASON}
               for row in value["availability"].values())
    assert value["authenticated"] is True
    assert value["videoStorage"]["limit"] == 25
    assert PRIVATE_DIAGNOSTIC not in response.text
    assert str(requests[0].url) not in response.text
    with closing(main.db()) as conn:
        assert conn.execute("SELECT token_balance FROM users WHERE id='video-user'").fetchone()[0] == 500
        assert [conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in ("jobs", "token_ledger", "images")] == before


def test_offline_cloud_does_not_remove_enabled_local_video_or_expose_guest_quota(config_api, monkeypatch):
    failing_catalog(monkeypatch)
    monkeypatch.setattr(main, "LOCAL_LTX_ENABLED", True)
    del config_api.cookies["onenode_session"]

    response = config_api.get("/api/video/config")

    assert response.status_code == 200
    value = response.json()
    assert value["catalog"]["status"] == "unavailable"
    assert value["modes"]["text_to_video"][0]["id"] == "local/ltx-2.3-fast-q3"
    assert value["availability"]["text_to_video"] == {"enabled": 1, "tariff": 1, "reason": ""}
    assert value["authenticated"] is False
    assert value["videoSlots"] == 0
    assert value["videoStorage"] == {"used": 0, "limit": 0, "free": 0, "full": False, "storedBytes": 0}


def test_healthy_catalog_keeps_model_price_and_original_availability(config_api):
    response = config_api.get("/api/video/config")

    assert response.status_code == 200
    value = response.json()
    assert value["catalog"] == {"status": "available", "reasonCode": None}
    assert value["modes"]["text_to_video"][0]["id"] == MODEL["id"]
    assert value["modes"]["text_to_video"][0]["publicPricing"]["fromTokens"] > 0
    assert value["availability"]["text_to_video"]["enabled"] == 1
    assert value["availability"]["reference_to_video"]["reason"] == "В админке не включены модели для этого режима."
    assert value["exchange"]["usdRub"] == 80.0


@pytest.mark.parametrize("blocked", ("catalog", "exchange"))
def test_config_deadline_cancels_pending_refresh_and_preserves_cached_rate(config_api, monkeypatch, blocked):
    cancelled = []
    settings = main._saved_setting
    monkeypatch.setattr(main, "_saved_setting", lambda key: {
        "rate": 73.0, "source": "owned-cache", "fetchedAt": "2026-01-01T00:00:00Z",
    } if key == "exchange_usd_rub" else settings(key))
    monkeypatch.setattr(video_presentation, "CONFIG_REFRESH_TIMEOUT_SECONDS", 0.01)

    async def held():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(blocked)

    monkeypatch.setattr(main, "fetch_openrouter_video_catalog" if blocked == "catalog" else "fetch_usd_rub_rate", held)
    response = config_api.get("/api/video/config")

    assert response.status_code == 200
    assert cancelled == [blocked]
    assert response.json()["exchange"] == {
        "usdRub": 73.0, "source": "owned-cache", "fetchedAt": "2026-01-01T00:00:00Z",
    }
    assert response.json()["catalog"]["status"] == ("unavailable" if blocked == "catalog" else "available")
    assert bool(response.json()["modes"]["text_to_video"]) is (blocked == "exchange")


def test_unexpected_application_error_is_not_disguised_as_provider_unavailability(config_api, monkeypatch):
    async def broken():
        raise RuntimeError("owned application invariant failed")

    monkeypatch.setattr(main, "fetch_openrouter_video_catalog", broken)
    with pytest.raises(RuntimeError, match="owned application invariant failed"):
        config_api.get("/api/video/config")
