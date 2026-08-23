from __future__ import annotations

import asyncio

from app.services import assistant_runtime


def _config(improve_route: str, voice_route: str = "api") -> dict:
    return {
        "improve": {"route": improve_route, "localModel": "gemma4:12b"},
        "voice": {"route": voice_route, "localModel": "gemma4:12b"},
    }


def test_local_route_is_warmed_and_kept_resident(monkeypatch):
    controller = assistant_runtime.OllamaResidencyController()
    calls: list[str] = []

    async def ensure(**kwargs):
        calls.append(kwargs["model"])
        return {"ok": True, "model": kwargs["model"], "alreadyResident": False}

    monkeypatch.setattr(assistant_runtime, "ensure_ollama_model_resident", ensure)
    result = asyncio.run(controller.sync(_config("local")))
    assert result["model"] == "gemma4:12b"
    assert calls == ["gemma4:12b"]


def test_api_only_route_releases_selected_local_model(monkeypatch):
    controller = assistant_runtime.OllamaResidencyController()
    released: list[str] = []

    async def status():
        return {"ok": True, "models": [{"name": "gemma4:12b"}]}

    async def unload(*, model: str):
        released.append(model)

    monkeypatch.setattr(assistant_runtime, "fetch_ollama_residency_status", status)
    monkeypatch.setattr(assistant_runtime, "unload_ollama_model", unload)
    result = asyncio.run(controller.sync(_config("api")))
    assert result == {"ok": True, "model": None, "released": 1}
    assert released == ["gemma4:12b"]
