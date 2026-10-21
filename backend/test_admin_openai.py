"""Isolated trusted-admin contract tests; never reach a real provider."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager

import httpx
import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"
from fastapi import FastAPI, HTTPException

from app.api.routers.admin_openai import (
    AdminOpenAIDependencies, create_admin_openai_router,
)
from app.integrations.openai import OpenAIProviderError


@pytest.fixture
def admin_client():
    settings = {}
    keys = {}
    audit = []
    state = {"admin": True}

    @contextmanager
    def fake_db():
        connection = sqlite3.connect(":memory:")
        try:
            yield connection
        finally:
            connection.close()

    def require_admin(_request):
        if not state["admin"]:
            raise HTTPException(403, "Forbidden")
        return {"internal_user_id": "test-admin"}

    def record_audit(_conn, action, **kwargs):
        audit.append((action, kwargs))

    async def probe(*, key, model):
        assert key == keys.get("key")
        return {"ok": True, "verified": True, "model": model}

    deps = AdminOpenAIDependencies(
        require_admin=require_admin,
        get_settings=lambda: settings.copy(),
        save_settings=lambda value: (settings.clear(), settings.update(value)),
        db=fake_db,
        audit=record_audit,
        secret_ready=lambda: {"ready": True},
        secret_exists=lambda: "key" in keys,
        secret_get=lambda: keys.get("key", ""),
        secret_set=lambda value: keys.update(key=value),
        secret_delete=lambda: keys.pop("key", None) is not None,
        probe=probe,
    )
    app = FastAPI()
    app.include_router(create_admin_openai_router(deps), prefix="/api/admin")
    return app, settings, keys, audit, state


@pytest.mark.anyio
async def test_full_admin_key_settings_verify_delete(admin_client):
    app, settings, keys, audit, state = admin_client
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        result = await client.get("/api/admin/openai")
        assert result.status_code == 200
        assert result.json()["enabled"] is False
        assert result.json()["keyConfigured"] is False
        premature = await client.put("/api/admin/openai/settings", json={"enabled": True, "model": "gpt-4.1-mini", "reason": "manual testing"})
        assert premature.status_code == 409
        invalid = await client.put("/api/admin/openai/key", json={"key": "sk-admin-super-secret", "reason": "manual testing"})
        assert invalid.status_code == 400
        sample_key = "sk-proj-isolated-example-key-do-not-use"
        saved = await client.put("/api/admin/openai/key", json={"key": sample_key, "reason": "manual testing"})
        assert saved.status_code == 200
        assert saved.json()["keyConfigured"] is True
        assert sample_key not in saved.text
        enabled = await client.put("/api/admin/openai/settings", json={"enabled": True, "model": "gpt-4.1-mini", "reason": "manual testing"})
        assert enabled.status_code == 200
        assert enabled.json()["enabled"] is True
        check = await client.post("/api/admin/openai/verify", json={"reason": "manual testing"})
        assert check.status_code == 200
        assert check.json()["verified"] is True
        assert all(sample_key not in str(item) for item in audit)
        state["admin"] = False
        assert (await client.get("/api/admin/openai")).status_code == 403
        assert (await client.request("DELETE", "/api/admin/openai/key", json={"reason": "manual testing"})).status_code == 403
        state["admin"] = True
        removed = await client.request("DELETE", "/api/admin/openai/key", json={"reason": "manual testing"})
        assert removed.status_code == 200
        assert removed.json()["keyConfigured"] is False
        assert removed.json()["enabled"] is False
        assert keys == {}
        assert settings["enabled"] is False
        assert [item[0] for item in audit] == ["openai_key_saved", "openai_settings_changed", "openai_access_probe", "openai_key_deleted"]


@pytest.mark.anyio
async def test_invalid_model_is_rejected_without_writes(admin_client):
    app, settings, keys, audit, state = admin_client
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        result = await client.put("/api/admin/openai/settings", json={"enabled": False, "model": "unknown", "reason": "manual testing"})
        assert result.status_code == 400
    assert settings == {}
    assert audit == []



def test_secretless_snapshot(admin_client):
    app, _settings, _keys, _audit, _state = admin_client
    assert not any("password" in str(route.path).lower() for route in app.routes)
