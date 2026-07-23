"""Admin notification center and social-syndication configuration routes."""

from __future__ import annotations

import sqlite3
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ...services.admin_notifications import list_notifications, mark_notifications_read


class NotificationsReadRequest(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=200)


class SettingsRequest(BaseModel):
    settings: dict[str, Any]


@dataclass(frozen=True)
class AdminOperationsDependencies:
    db: Callable[[], AbstractContextManager[sqlite3.Connection]]
    require_admin: Callable[[Request], dict[str, Any]]
    saved_setting: Callable[[str], dict[str, Any]]
    save_setting: Callable[[str, dict[str, Any]], None]
    record_audit: Callable[..., None]
    fetch_openrouter_key_status: Callable[[], Awaitable[dict[str, Any]]]
    openrouter_usage_stats: Callable[[], dict[str, Any]]
    get_openrouter_config: Callable[[], dict[str, Any]]
    fetch_usd_rub_rate: Callable[[], Awaitable[dict[str, Any]]]
    openrouter_catalog_snapshot: Callable[[], dict[str, Any]]
    schedule_openrouter_catalog_refresh: Callable[[], bool]
    openrouter_economy_settings: Callable[[], dict[str, Any]]
    openrouter_price_catalog: Callable[[], dict[str, Any]]


def create_admin_operations_router(deps: AdminOperationsDependencies) -> APIRouter:
    router = APIRouter(prefix="/api/admin")

    @router.get("/openrouter/status")
    async def openrouter_status(request: Request) -> dict[str, Any]:
        deps.require_admin(request)
        return {
            "key": await deps.fetch_openrouter_key_status(),
            "usage": deps.openrouter_usage_stats(),
            "config": deps.get_openrouter_config(),
            "exchange": await deps.fetch_usd_rub_rate(),
        }

    @router.get("/openrouter/catalog/status-v2")
    async def openrouter_catalog_status(request: Request) -> dict[str, Any]:
        deps.require_admin(request)
        return {"ok": True, "catalog": deps.openrouter_catalog_snapshot()["meta"]}

    @router.post("/openrouter/catalog/refresh-v2")
    async def openrouter_catalog_refresh(request: Request) -> dict[str, Any]:
        deps.require_admin(request)
        started = deps.schedule_openrouter_catalog_refresh()
        return {
            "ok": True,
            "started": started,
            "alreadyRunning": not started,
            "catalog": deps.openrouter_catalog_snapshot()["meta"],
        }

    @router.get("/openrouter/pricing")
    async def openrouter_pricing(request: Request) -> dict[str, Any]:
        deps.require_admin(request)
        exchange = await deps.fetch_usd_rub_rate()
        economy = deps.openrouter_economy_settings()
        return {
            "ok": True,
            "exchange": exchange,
            "economy": economy,
            "fee": {"usdFeePercent": economy["usdFeePercent"]},
            "models": [model.model_dump() for model in deps.openrouter_price_catalog().values()],
        }

    @router.get("/notifications-v2")
    async def notifications(
        request: Request, unread_only: bool = False, limit: int = 100
    ) -> dict[str, Any]:
        deps.require_admin(request)
        with deps.db() as conn:
            return {"ok": True, **list_notifications(conn, unread_only=unread_only, limit=limit)}

    @router.post("/notifications/read-v2")
    async def notifications_read(req: NotificationsReadRequest, request: Request) -> dict[str, Any]:
        actor = deps.require_admin(request)
        with deps.db() as conn:
            changed = mark_notifications_read(conn, req.ids)
            deps.record_audit(
                conn,
                "admin_notifications_mark_read",
                actor_internal_user_id=actor.get("internal_user_id"),
                entity_type="admin_notification",
                after={"ids": req.ids, "changed": changed},
                request=request,
            )
            unread = list_notifications(conn, unread_only=True, limit=1)["unread"]
        return {"ok": True, "changed": changed, "unread": unread}

    @router.get("/notifications/settings-v2")
    async def notification_settings(request: Request) -> dict[str, Any]:
        deps.require_admin(request)
        saved = deps.saved_setting("admin_notification_settings")
        return {"ok": True, "settings": {
            "inAppEnabled": bool(saved.get("inAppEnabled", True)),
            "telegramEnabled": bool(saved.get("telegramEnabled", False)),
            "emailEnabled": bool(saved.get("emailEnabled", False)),
            "minimumSeverity": str(saved.get("minimumSeverity") or "info"),
            "digestMode": str(saved.get("digestMode") or "immediate"),
            "quietHours": saved.get("quietHours") or {
                "enabled": False, "from": "22:00", "to": "08:00"
            },
            "categories": saved.get("categories") or {},
        }}

    @router.put("/notifications/settings-v2")
    async def save_notification_settings(req: SettingsRequest, request: Request) -> dict[str, Any]:
        actor = deps.require_admin(request)
        settings = {
            "inAppEnabled": bool(req.settings.get("inAppEnabled", True)),
            "telegramEnabled": bool(req.settings.get("telegramEnabled", False)),
            "emailEnabled": bool(req.settings.get("emailEnabled", False)),
            "minimumSeverity": str(req.settings.get("minimumSeverity") or "info"),
            "digestMode": str(req.settings.get("digestMode") or "immediate"),
            "quietHours": req.settings.get("quietHours") or {
                "enabled": False, "from": "22:00", "to": "08:00"
            },
            "categories": req.settings.get("categories") or {},
        }
        if settings["minimumSeverity"] not in {"info", "warning", "critical"}:
            raise HTTPException(400, "Некорректный уровень уведомлений.")
        if settings["digestMode"] not in {"immediate", "daily"}:
            raise HTTPException(400, "Некорректный режим доставки.")
        deps.save_setting("admin_notification_settings", settings)
        with deps.db() as conn:
            deps.record_audit(
                conn, "admin_notification_settings_update",
                actor_internal_user_id=actor.get("internal_user_id"),
                entity_type="admin_settings", entity_id="admin_notification_settings",
                after=settings, request=request,
            )
        return {"ok": True, "settings": settings}

    @router.get("/social-v2")
    async def social(request: Request) -> dict[str, Any]:
        deps.require_admin(request)
        saved = deps.saved_setting("social_syndication")
        networks = saved.get("networks") if isinstance(saved.get("networks"), dict) else {}
        with deps.db() as conn:
            rows = conn.execute(
                "SELECT network, status, COUNT(*) AS count FROM social_delivery_outbox "
                "GROUP BY network, status ORDER BY network, status"
            ).fetchall()
        return {
            "ok": True,
            "settings": {
                "masterEnabled": bool(saved.get("masterEnabled", False)),
                "autoPublish": bool(saved.get("autoPublish", False)),
                "networks": {
                    name: {"enabled": bool((networks.get(name) or {}).get("enabled", False))}
                    for name in ("telegram", "vk", "instagram", "ok")
                },
            },
            "queue": [dict(row) for row in rows],
            "operational": False,
            "message": "Внешняя доставка выключена до подключения провайдеров.",
        }

    @router.put("/social-v2")
    async def save_social(req: SettingsRequest, request: Request) -> dict[str, Any]:
        actor = deps.require_admin(request)
        source = req.settings.get("networks") if isinstance(req.settings.get("networks"), dict) else {}
        settings = {
            "masterEnabled": False,
            "autoPublish": bool(req.settings.get("autoPublish", False)),
            "networks": {
                name: {"enabled": bool((source.get(name) or {}).get("enabled", False))}
                for name in ("telegram", "vk", "instagram", "ok")
            },
        }
        deps.save_setting("social_syndication", settings)
        with deps.db() as conn:
            deps.record_audit(
                conn, "admin_social_settings_update",
                actor_internal_user_id=actor.get("internal_user_id"),
                entity_type="admin_settings", entity_id="social_syndication",
                after=settings, request=request,
            )
        return {
            "ok": True, "settings": settings, "operational": False,
            "message": "Настройки сохранены без включения внешней доставки.",
        }

    return router
