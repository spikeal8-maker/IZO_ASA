"""Trusted OpenAI administration: credential operations, status, and read-only access probe."""
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

import sqlite3
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ...integrations.openai import (
    DEFAULT_MODEL, SUPPORTED_MODELS, OpenAIProviderError,
    check_openai_access, normalize_openai_settings,
)
from ...security.openai_secrets import (
    OpenAISecretStoreError, delete_openai_key, get_openai_key,
    has_openai_key, openai_secret_store_status, set_openai_key,
)


class SaveKeyRequest(BaseModel):
    key: str = Field(min_length=12, max_length=4096)
    reason: str = Field(min_length=8, max_length=200)


class OpenAISettingsRequest(BaseModel):
    enabled: bool
    model: str = Field(min_length=3, max_length=100)
    reason: str = Field(min_length=8, max_length=200)


class OpenAIActionRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=200)


@dataclass(frozen=True)
class AdminOpenAIDependencies:
    require_admin: Callable[[Request], dict[str, Any]]
    get_settings: Callable[[], dict[str, Any]]
    save_settings: Callable[[dict[str, Any]], None]
    db: Callable[[], AbstractContextManager[sqlite3.Connection]]
    audit: Callable[..., None]
    secret_ready: Callable[[], dict[str, bool]] = openai_secret_store_status
    secret_exists: Callable[[], bool] = has_openai_key
    secret_get: Callable[[], str] = get_openai_key
    secret_set: Callable[[str], None] = set_openai_key
    secret_delete: Callable[[], bool] = delete_openai_key
    probe: Callable[..., Any] = check_openai_access


def create_admin_openai_router(deps: AdminOpenAIDependencies) -> APIRouter:
    router = APIRouter(prefix="/openai")

    def settings() -> dict[str, Any]:
        return normalize_openai_settings(deps.get_settings())

    def snapshot() -> dict[str, Any]:
        store_ready = deps.secret_ready()["ready"]
        try:
            configured = deps.secret_exists() if store_ready else False
        except OpenAISecretStoreError:
            store_ready, configured = False, False
        return {
            "ok": True, "enabled": settings()["enabled"],
            "model": settings()["model"], "keyConfigured": configured,
            "secretStoreReady": store_ready,
            "models": [{"id": model, "label": model} for model in SUPPORTED_MODELS],
            "liveVerified": False,
        }

    def audit(request: Request, actor: dict[str, Any], action: str, before: dict | None, after: dict) -> None:
        with deps.db() as conn:
            deps.audit(
                conn, action, actor_internal_user_id=actor.get("internal_user_id"),
                entity_type="provider", entity_id="openai",
                before=before, after=after, request=request,
            )

    @router.get("")
    async def status(request: Request) -> dict[str, Any]:
        deps.require_admin(request)
        return snapshot()

    @router.put("/key")
    async def save_key(body: SaveKeyRequest, request: Request) -> dict[str, Any]:
        actor = deps.require_admin(request)
        # Refuse organization administration keys. This API accepts a project key.
        if not body.key.strip().startswith("sk-") or body.key.strip().startswith("sk-admin-"):
            raise HTTPException(400, "Введите проектный API-ключ OpenAI, не Admin API key.")
        try:
            deps.secret_set(body.key.strip())
        except (OpenAISecretStoreError, OSError) as exc:
            raise HTTPException(503, "Защищённое хранилище ключей OpenAI недоступно.") from exc
        audit(request, actor, "openai_key_saved", None, {"configured": True, "reason": "admin_ui"})
        return snapshot()

    @router.put("/settings")
    async def save_settings(body: OpenAISettingsRequest, request: Request) -> dict[str, Any]:
        actor = deps.require_admin(request)
        if body.model not in SUPPORTED_MODELS:
            raise HTTPException(400, "Недопустимая модель OpenAI.")
        if body.enabled:
            try:
                key_exists = deps.secret_exists()
            except OpenAISecretStoreError:
                key_exists = False
            if not key_exists:
                raise HTTPException(409, "Сначала сохраните ключ OpenAI.")
        before = settings()
        new = {"enabled": body.enabled, "model": body.model}
        deps.save_settings(new)
        audit(request, actor, "openai_settings_changed", before, {**new, "reason": "admin_ui"})
        return snapshot()

    @router.post("/verify")
    async def verify(body: OpenAIActionRequest, request: Request) -> dict[str, Any]:
        actor = deps.require_admin(request)
        try:
            key = deps.secret_get()
            result = await deps.probe(key=key, model=settings()["model"])
        except OpenAIProviderError as exc:
            audit(request, actor, "openai_access_probe", None, {"ok": False, "code": exc.code})
            raise HTTPException(exc.status, str(exc)) from exc
        except (OpenAISecretStoreError, OSError) as exc:
            raise HTTPException(503, "Хранилище ключей OpenAI недоступно.") from exc
        audit(request, actor, "openai_access_probe", None, {"ok": True, "model": result["model"]})
        return result

    @router.delete("/key")
    async def remove_key(body: OpenAIActionRequest, request: Request) -> dict[str, Any]:
        actor = deps.require_admin(request)
        prior = settings()
        # Disable first so an unsuccessful deletion cannot leave an enabled provider.
        deps.save_settings({"enabled": False, "model": prior["model"]})
        try:
            deleted = deps.secret_delete()
        except (OpenAISecretStoreError, OSError) as exc:
            audit(request, actor, "openai_key_delete_blocked", prior, {"enabled": False})
            raise HTTPException(503, "Не удалось удалить ключ. Провайдер выключен.") from exc
        audit(request, actor, "openai_key_deleted", prior, {"enabled": False, "deleted": deleted, "reason": "admin_ui"})
        return snapshot()

    return router
