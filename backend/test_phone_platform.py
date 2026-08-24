from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.api.routers.phone_platform import (
    PhonePlatformDependencies,
    create_phone_platform_router,
)
from app.services.phone_platform import phone_platform_manifest


def test_phone_platform_manifest_has_stable_routes_and_no_provider_internals(monkeypatch) -> None:
    monkeypatch.delenv("PHONE_3D_ENABLED", raising=False)
    payload = phone_platform_manifest()

    assert payload["apiVersion"] == "v1"
    assert payload["defaultRoute"] == "/phone/image"
    routes = {item["id"]: item for item in payload["workspaces"]}
    assert set(routes) == {"image", "video", "chat", "audio", "3d"}
    assert routes["audio"]["enabled"] is True
    assert routes["audio"]["operations"] == ["speech_to_text"]
    assert routes["3d"]["navigation"] == "menu"
    assert routes["3d"]["enabled"] is False
    serialized = str(payload).casefold()
    assert "checkpoint" not in serialized
    assert "provider" not in serialized
    assert "openrouter" not in serialized


def test_phone_platform_feature_flag_is_server_owned(monkeypatch) -> None:
    monkeypatch.setenv("PHONE_3D_ENABLED", "true")
    routes = {item["id"]: item for item in phone_platform_manifest()["workspaces"]}
    assert routes["3d"]["enabled"] is True


def test_phone_platform_route_requires_trusted_user() -> None:
    app = FastAPI()

    def reject(_request: Request):
        raise HTTPException(401, "trusted session required")

    app.include_router(create_phone_platform_router(PhonePlatformDependencies(reject)))
    response = TestClient(app).get("/api/phone/v1/platform")
    assert response.status_code == 401


def test_phone_platform_route_returns_manifest_for_trusted_user() -> None:
    app = FastAPI()
    app.include_router(
        create_phone_platform_router(
            PhonePlatformDependencies(lambda _request: {"internal_user_id": "user-1"})
        )
    )
    response = TestClient(app).get("/api/phone/v1/platform")
    assert response.status_code == 200
    assert response.json()["shell"]["nativeReact"] is True
