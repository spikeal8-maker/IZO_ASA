"""Trusted-admin key storage and fresh read-only checks without input reflection."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from contextlib import closing
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from ...security.secret_store import SecretStoreError


@dataclass(frozen=True)
class OpenRouterKeyDependencies:
    require_trusted_admin: Callable[[Request], Any]
    save: Callable[[str], None]
    delete: Callable[[], None]
    status: Callable[[], Awaitable[dict[str, Any]]]
    refresh_catalog: Callable[[], bool]
    usage: Callable[[], dict]
    config: Callable[[], dict]
    audit: Callable[[Any, str, str, Request], None]


def secret_auditor(connect: Callable, record_audit: Callable) -> Callable:
    def record(actor: dict, action: str, outcome: str, request: Request) -> None:
        with closing(connect()) as conn, conn:
            record_audit(conn, "admin_openrouter_key_" + action,
                         actor_internal_user_id=actor.get("internal_user_id"),
                         entity_type="provider_secret", entity_id="openrouter",
                         after={"outcome": outcome}, request=request)
    return record


async def _key_input(request: Request) -> str:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(415, "OPENROUTER_KEY_JSON_REQUIRED")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 2048:
            raise HTTPException(413, "OPENROUTER_KEY_REQUEST_TOO_LARGE")
    try:
        payload = json.loads(body)
        if not isinstance(payload, dict) or set(payload) != {"key"} or not isinstance(payload["key"], str):
            raise ValueError
        key = payload["key"].strip()
        if not 12 <= len(key) <= 512 or not re.fullmatch(r"sk-or-[A-Za-z0-9_-]+", key):
            raise ValueError
        return key
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(422, "OPENROUTER_KEY_FORMAT_INVALID") from None


def create_openrouter_key_router(deps: OpenRouterKeyDependencies) -> APIRouter:
    router = APIRouter()

    async def response(*, saved: bool = False, removed: bool = False) -> dict:
        try:
            status = await deps.status()
        except Exception:
            status = {"configured": True if saved else None, "ok": False, "verificationUnavailable": True,
                      "error": "Не удалось выполнить проверку ключа."}
        overridden = status.get("source") == "env"
        return {
            "ok": True, "keySaved": saved, "keyRemoved": removed,
            "keyVerified": bool(status.get("ok")) and not (saved and overridden),
            "environmentOverride": overridden, "key": status,
            "usage": deps.usage(), "config": deps.config(),
        }

    @router.put("/api/admin/openrouter/key")
    async def save(request: Request) -> JSONResponse:
        actor = deps.require_trusted_admin(request)
        key = await _key_input(request)
        try:
            await asyncio.to_thread(deps.save, key)
        except SecretStoreError:
            deps.audit(actor, "save", "unconfirmed", request)
            raise HTTPException(503, "OPENROUTER_KEY_SAVE_UNCONFIRMED") from None
        deps.audit(actor, "save", "stored", request)
        result = await response(saved=True)
        try:
            result["catalogRefreshStarted"] = deps.refresh_catalog()
        except Exception:
            result["catalogRefreshStarted"] = False
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @router.get("/api/admin/openrouter/key")
    async def check(request: Request) -> JSONResponse:
        deps.require_trusted_admin(request)
        return JSONResponse(await response(), headers={"Cache-Control": "no-store"})

    @router.delete("/api/admin/openrouter/key")
    async def delete(request: Request) -> JSONResponse:
        actor = deps.require_trusted_admin(request)
        try:
            await asyncio.to_thread(deps.delete)
        except SecretStoreError:
            deps.audit(actor, "delete", "unconfirmed", request)
            raise HTTPException(503, "OPENROUTER_KEY_DELETE_UNCONFIRMED") from None
        deps.audit(actor, "delete", "removed", request)
        result = await response(removed=True)
        try:
            result["catalogRefreshStarted"] = deps.refresh_catalog()
        except Exception:
            result["catalogRefreshStarted"] = False
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    return router
