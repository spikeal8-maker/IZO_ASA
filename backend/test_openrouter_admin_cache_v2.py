from __future__ import annotations

import asyncio
import inspect

import pytest

import main


def reset_openrouter_caches() -> None:
    main._openrouter_capability_cache.update({"ts": 0.0, "models": []})
    main._openrouter_video_catalog_cache.update({"ts": 0.0, "models": []})
    main._openrouter_key_status_cache.update({"ts": 0.0, "data": None, "keyMarker": None})
    main._openrouter_catalog_state.update(
        {
            "refreshing": False,
            "lastAttemptAt": None,
            "lastSuccessAt": None,
            "lastError": None,
            "source": "fallback",
            "modelCount": 0,
            "videoModelCount": 0,
        }
    )
    main._openrouter_catalog_refresh_task = None
    main._admin_models_page_cache.update({"ts": {"api": 10.0}, "data": {"api": {"ok": True}}})


def test_invalidation_keeps_last_successful_catalog():
    reset_openrouter_caches()
    models = [{"id": "safe/model", "name": "Safe"}]
    main._openrouter_capability_cache.update({"ts": 100.0, "models": models})
    main.invalidate_openrouter_admin_caches(authorization_changed=True)
    assert main._openrouter_capability_cache["models"] == models
    assert main._openrouter_capability_cache["ts"] == 0.0
    assert main._admin_models_page_cache == {"ts": {}, "data": {}}


def test_snapshot_uses_fallback_without_network():
    reset_openrouter_caches()
    snapshot = main.openrouter_catalog_snapshot()
    assert snapshot["meta"]["source"] == "fallback"
    assert snapshot["meta"]["modelCount"] > 0
    assert snapshot["models"]


def test_fallback_catalog_does_not_strip_saved_modes():
    reset_openrouter_caches()
    requested = {
        "enabled": {"edit": ["provider/model"]},
        "defaults": {"edit": "provider/model"},
    }
    normalized = main.normalize_openrouter_config(requested)
    assert normalized["enabled"]["edit"] == ["provider/model"]
    assert normalized["defaults"]["edit"] == "provider/model"
    assert normalized["published"] == ["provider/model"]


def test_global_unpublish_removes_operation_tariff_and_defaults():
    normalized = main.normalize_openrouter_config({
        "published": ["provider/visible"],
        "enabled": {"edit": ["provider/visible", "provider/hidden"]},
        "defaults": {"edit": "provider/hidden"},
        "access": {"edit": {"pro": ["provider/visible", "provider/hidden"]}},
        "qualityDefaults": {"edit": {"max": "provider/hidden"}},
    })
    assert normalized["published"] == ["provider/visible"]
    assert normalized["enabled"]["edit"] == ["provider/visible"]
    assert normalized["defaults"]["edit"] == "provider/visible"
    assert normalized["access"]["edit"]["pro"] == ["provider/visible"]
    assert normalized["qualityDefaults"]["edit"]["max"] == "provider/visible"


def test_server_rejects_unpublished_or_operation_disabled_model():
    config = main.normalize_openrouter_config({
        "published": ["provider/allowed", "provider/wrong-mode"],
        "enabled": {"edit": ["provider/allowed"], "text_to_image": ["provider/wrong-mode"]},
        "access": {"edit": {"pro": ["provider/allowed"]}, "text_to_image": {"pro": ["provider/wrong-mode"]}},
    })
    assert main.openrouter_model_allowed(config, "edit", "pro", "provider/allowed") is True
    assert main.openrouter_model_allowed(config, "edit", "pro", "provider/wrong-mode") is False
    unpublished = {**config, "published": []}
    assert main.openrouter_model_allowed(unpublished, "edit", "pro", "provider/allowed") is False


def test_exchange_snapshot_never_uses_network(monkeypatch):
    monkeypatch.setattr(main, "_saved_setting", lambda _key: {})

    class NetworkMustNotRun:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("network client was created")

    monkeypatch.setattr(main.httpx, "AsyncClient", NetworkMustNotRun)
    snapshot = main.usd_rub_rate_snapshot()
    assert snapshot["rate"] is None
    assert snapshot["cache"] == "empty"


def test_models_page_first_response_does_not_await_external_catalogs():
    source = inspect.getsource(main.admin_models_page)
    assert "await fetch_openrouter" not in source
    assert "await fetch_usd_rub_rate" not in source
    assert "schedule_openrouter_catalog_refresh()" in source


def test_failed_live_fetch_does_not_delete_cached_models(monkeypatch):
    reset_openrouter_caches()
    models = [{"id": "last/success", "name": "Last success"}]
    main._openrouter_capability_cache.update({"ts": 1.0, "models": models})

    async def fail_fetch(**_kwargs):
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(main, "fetch_openrouter_image_model_documents", fail_fetch)
    with pytest.raises(RuntimeError):
        asyncio.run(main.fetch_openrouter_image_capabilities(force=True))
    assert main._openrouter_capability_cache["models"] == models


def test_parallel_refresh_requests_share_one_task(monkeypatch):
    reset_openrouter_caches()
    calls = {"key": 0, "image": 0, "video": 0}

    async def key_status(force: bool = False):
        calls["key"] += 1
        await asyncio.sleep(0.01)
        return {"configured": True, "ok": True}

    async def image_catalog(force: bool = False):
        calls["image"] += 1
        await asyncio.sleep(0.01)
        main._openrouter_capability_cache.update(
            {"ts": main.time.monotonic(), "models": [{"id": "live/model"}]}
        )
        return main._openrouter_capability_cache["models"]

    async def video_catalog(force: bool = False):
        calls["video"] += 1
        await asyncio.sleep(0.01)
        main._openrouter_video_catalog_cache.update(
            {"ts": main.time.monotonic(), "models": [{"id": "live/video"}]}
        )
        return main._openrouter_video_catalog_cache["models"]

    monkeypatch.setattr(main, "fetch_openrouter_key_status", key_status)
    monkeypatch.setattr(main, "fetch_openrouter_image_capabilities", image_catalog)
    monkeypatch.setattr(main, "fetch_openrouter_video_catalog", video_catalog)

    async def run() -> None:
        assert main.schedule_openrouter_catalog_refresh() is True
        assert main.schedule_openrouter_catalog_refresh() is False
        assert main._openrouter_catalog_refresh_task is not None
        await main._openrouter_catalog_refresh_task

    asyncio.run(run())
    assert calls == {"key": 1, "image": 1, "video": 1}
    assert main._openrouter_catalog_state["lastError"] is None
    assert main._openrouter_catalog_state["modelCount"] == 1


def test_frontend_bots_route_and_secret_controls_are_present():
    admin_app = (main.ROOT.parent / "frontend" / "src" / "AdminApp.tsx").read_text(encoding="utf-8")
    bots_page = (main.ROOT.parent / "frontend" / "src" / "adminBots.tsx").read_text(encoding="utf-8")
    assert admin_app.index("path: '/admin/mail'") < admin_app.index("path: '/admin/bots'") < admin_app.index("path: '/admin/logs'")
    assert 'type="password"' in bots_page
    assert "confirmModeChange" in bots_page
    assert "window.confirm" in bots_page
    assert "setTokens((current) => ({ ...current, [provider]: '' }))" in bots_page


def test_frontend_model_catalog_uses_server_publication_contract():
    frontend = main.ROOT.parent / "frontend" / "src"
    support = (frontend / "profileSupport.ts").read_text(encoding="utf-8")
    studio = (frontend / "newUi.tsx").read_text(encoding="utf-8")
    profile = (frontend / "ProfilePage.tsx").read_text(encoding="utf-8")
    admin = (frontend / "adminModels.tsx").read_text(encoding="utf-8")
    assert "publishedModels: ModelOption[]" in support
    assert "currentModeAccess?.publishedModels || currentModeAccess?.models" in studio
    assert "modelAccess.modes[mode]?.publishedModels || accessModels" in profile
    assert "toggleOpenrouterPublished" in admin
    assert "Глобальная публикация" in admin
