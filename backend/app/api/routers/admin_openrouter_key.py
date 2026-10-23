"""Trusted OpenRouter API-key operations; persist-first and explicit read-only check."""
from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field


class SaveKeyRequest(BaseModel):
    key: str = Field(min_length=12, max_length=4096)


@dataclass(frozen=True)
class OpenRouterKeyDependencies:
    require_admin: Callable[[Request], dict[str, Any]]
    store_ready: Callable[[], bool]
    store_exists: Callable[[], bool]
    get_key: Callable[[], str]
    save_key: Callable[[str], None]
    delete_key: Callable[[], None]
    verify: Callable[[], Awaitable[dict[str, Any]]]
    db: Callable[[], Any]
    audit: Callable[..., None]
    secret_error: type[Exception]


async def save_openrouter_key(deps: OpenRouterKeyDependencies, body: SaveKeyRequest, request: Request) -> dict[str, Any]:
    actor = deps.require_admin(request)
    key = body.key.strip()
    if not key.startswith("sk-or-"):
        raise HTTPException(400, "Нужен API-ключ OpenRouter формата sk-or-...")
    if not deps.store_ready():
        raise HTTPException(503, "Защищённое хранилище OpenRouter недоступно.")
    try:
        deps.save_key(key)
        if not hmac.compare_digest(deps.get_key(), key):
            raise deps.secret_error("SECRET_READBACK_FAILED")
    except deps.secret_error as exc:
        raise HTTPException(503, "Не удалось сохранить ключ OpenRouter.") from exc
    with deps.db() as conn:
        deps.audit(
            conn, "openrouter_key_saved", actor_internal_user_id=actor["internal_user_id"],
            entity_type="provider", entity_id="openrouter",
            after={"configured": True}, request=request,
        )
    return {
        "ok": True, "keySaved": True, "keyConfigured": True,
        "secretStoreReady": True, "liveVerified": False,
        "verification": {"state": "not_checked"},
    }


async def check_openrouter_key(deps: OpenRouterKeyDependencies, request: Request) -> dict[str, Any]:
    deps.require_admin(request)
    try:
        status = await deps.verify()
    except deps.secret_error:
        return {"ok": False, "state": "storage_unavailable", "keyConfigured": False,
                "secretStoreReady": False, "liveVerified": False}
    code = status.get("status_code")
    return {
        "ok": status.get("ok") is True, "keyConfigured": status.get("configured") is True,
        "secretStoreReady": status.get("secretStoreReady", False),
        "liveVerified": status.get("liveVerified") is True,
        "status_code": code, "error": status.get("error"),
        "state": "verified" if status.get("liveVerified") else
            "invalid_key" if code == 401 else
            "network_unavailable" if code is None else "provider_rejected",
    }


async def delete_openrouter_key(deps: OpenRouterKeyDependencies, request: Request) -> dict[str, Any]:
    actor = deps.require_admin(request)
    try:
        deps.delete_key()
        if deps.store_exists():
            raise deps.secret_error("SECRET_DELETION_NOT_CONFIRMED")
    except deps.secret_error as exc:
        raise HTTPException(503, "Не удалось удалить ключ OpenRouter.") from exc
    with deps.db() as conn:
        deps.audit(
            conn, "openrouter_key_deleted", actor_internal_user_id=actor["internal_user_id"],
            entity_type="provider", entity_id="openrouter",
            after={"configured": False}, request=request,
        )
    return {"ok": True, "keySaved": False, "keyConfigured": False, "liveVerified": False}
