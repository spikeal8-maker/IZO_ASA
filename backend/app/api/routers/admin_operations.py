"""Admin notification center and social-syndication configuration routes."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ...services.admin_notifications import list_notifications, mark_notifications_read
from ...integrations.social_providers import SocialProviderError


class NotificationsReadRequest(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=200)


class SettingsRequest(BaseModel):
    settings: dict[str, Any]


def _valid_email(value: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value))


def _notification_delivery_status(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT channel, status, COUNT(*) AS count, MAX(sent_at) AS last_sent_at "
        "FROM admin_notification_delivery_outbox "
        "GROUP BY channel, status ORDER BY channel, status"
    ).fetchall()
    return [dict(row) for row in rows]


class SocialCredentialsRequest(BaseModel):
    token: str = Field(default="", max_length=4096)
    targetId: str = Field(default="", max_length=300)
    applicationKey: str = Field(default="", max_length=500)
    sessionSecret: str = Field(default="", max_length=4096)


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
    fetch_usd_rub_rate: Callable[..., Awaitable[dict[str, Any]]]
    openrouter_catalog_snapshot: Callable[[], dict[str, Any]]
    schedule_openrouter_catalog_refresh: Callable[[], bool]
    openrouter_economy_settings: Callable[[], dict[str, Any]]
    openrouter_price_catalog: Callable[[], dict[str, Any]]
    invalidate_openrouter_admin_caches: Callable[[], None]
    secret_exists: Callable[[str], bool]
    secret_get: Callable[[str], str]
    secret_set: Callable[[str, str], None]
    secret_delete: Callable[[str], bool]
    probe_social: Callable[..., Any]
    notification_worker_status: Callable[[], dict[str, Any]] = lambda: {
        "running": False,
        "lastSuccessAt": None,
        "lastErrorAt": None,
        "lastError": None,
    }


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

    @router.post("/openrouter/exchange/refresh")
    async def openrouter_exchange_refresh(request: Request) -> dict[str, Any]:
        deps.require_admin(request)
        exchange = await deps.fetch_usd_rub_rate(force=True)
        deps.invalidate_openrouter_admin_caches()
        return {"ok": isinstance(exchange.get("rate"), (int, float)), "exchange": exchange}

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
        with deps.db() as conn:
            delivery = _notification_delivery_status(conn)
        return {
            "ok": True,
            "settings": {
                "inAppEnabled": bool(saved.get("inAppEnabled", True)),
                "telegramEnabled": bool(saved.get("telegramEnabled", False)),
                "telegramChatId": str(saved.get("telegramChatId") or ""),
                "emailEnabled": bool(saved.get("emailEnabled", False)),
                "emailAddress": str(saved.get("emailAddress") or ""),
                "minimumSeverity": str(saved.get("minimumSeverity") or "info"),
                "digestMode": str(saved.get("digestMode") or "immediate"),
                "quietHours": saved.get("quietHours") or {
                    "enabled": False, "from": "22:00", "to": "08:00"
                },
                "categories": saved.get("categories") or {},
            },
            "delivery": delivery,
            "worker": deps.notification_worker_status(),
        }

    @router.put("/notifications/settings-v2")
    async def save_notification_settings(req: SettingsRequest, request: Request) -> dict[str, Any]:
        actor = deps.require_admin(request)
        telegram_chat_id = str(req.settings.get("telegramChatId") or "").strip()
        email_address = str(req.settings.get("emailAddress") or "").strip().lower()
        settings = {
            "inAppEnabled": bool(req.settings.get("inAppEnabled", True)),
            "telegramEnabled": bool(req.settings.get("telegramEnabled", False)),
            "telegramChatId": telegram_chat_id,
            "emailEnabled": bool(req.settings.get("emailEnabled", False)),
            "emailAddress": email_address,
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
        if settings["telegramEnabled"] and not telegram_chat_id:
            raise HTTPException(400, "Укажите Telegram chat ID администратора.")
        if settings["emailEnabled"] and not _valid_email(email_address):
            raise HTTPException(400, "Укажите корректный email администратора.")
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
        configured = {
            name: deps.secret_exists(f"social_{name}_access_token")
            for name in ("telegram", "vk", "instagram", "ok")
        }
        return {
            "ok": True,
            "settings": {
                "masterEnabled": bool(saved.get("masterEnabled", False)),
                "autoPublish": bool(saved.get("autoPublish", False)),
                "networks": {
                    name: {
                        "enabled": bool((networks.get(name) or {}).get("enabled", False)),
                        "configured": configured[name],
                        "targetId": str((networks.get(name) or {}).get("targetId") or ""),
                        "applicationKey": str((networks.get(name) or {}).get("applicationKey") or ""),
                        "verified": bool((networks.get(name) or {}).get("verified", False)),
                        "lastCheckedAt": (networks.get(name) or {}).get("lastCheckedAt"),
                        "lastError": (networks.get(name) or {}).get("lastError"),
                    }
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
                name: {
                    **(deps.saved_setting("social_syndication").get("networks", {}).get(name, {})),
                    "enabled": bool((source.get(name) or {}).get("enabled", False)),
                    "targetId": str((source.get(name) or {}).get("targetId") or ""),
                    "applicationKey": str((source.get(name) or {}).get("applicationKey") or ""),
                }
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
            "message": "Настройки сохранены. Публикация включается после проверки доступов.",
        }

    @router.put("/social/{network}/credentials-v2")
    async def save_social_credentials(
        network: str, req: SocialCredentialsRequest, request: Request
    ) -> dict[str, Any]:
        actor = deps.require_admin(request)
        if network not in {"telegram", "vk", "instagram", "ok"}:
            raise HTTPException(404, "Социальная сеть не поддерживается.")
        if req.token.strip():
            deps.secret_set(f"social_{network}_access_token", req.token.strip())
        if network == "ok" and req.sessionSecret.strip():
            deps.secret_set("social_ok_session_secret", req.sessionSecret.strip())
        if not deps.secret_exists(f"social_{network}_access_token"):
            raise HTTPException(400, "Введите ключ доступа.")
        saved = deps.saved_setting("social_syndication")
        networks = saved.get("networks") if isinstance(saved.get("networks"), dict) else {}
        networks[network] = {
            **(networks.get(network) or {}),
            "targetId": req.targetId.strip(),
            "applicationKey": req.applicationKey.strip(),
            "verified": False,
            "lastError": None,
        }
        saved["networks"] = networks
        deps.save_setting("social_syndication", saved)
        with deps.db() as conn:
            deps.record_audit(
                conn, "admin_social_credentials_update",
                actor_internal_user_id=actor.get("internal_user_id"),
                entity_type="social_provider", entity_id=network,
                after={"configured": True, "targetId": req.targetId.strip()},
                request=request,
            )
        return {"ok": True, "configured": True}

    @router.delete("/social/{network}/credentials-v2")
    async def delete_social_credentials(network: str, request: Request) -> dict[str, Any]:
        actor = deps.require_admin(request)
        if network not in {"telegram", "vk", "instagram", "ok"}:
            raise HTTPException(404, "Социальная сеть не поддерживается.")
        deleted = deps.secret_delete(f"social_{network}_access_token")
        if network == "ok":
            deleted = deps.secret_delete("social_ok_session_secret") or deleted
        saved = deps.saved_setting("social_syndication")
        networks = saved.get("networks") if isinstance(saved.get("networks"), dict) else {}
        networks[network] = {**(networks.get(network) or {}), "enabled": False, "verified": False}
        saved["networks"] = networks
        deps.save_setting("social_syndication", saved)
        with deps.db() as conn:
            deps.record_audit(
                conn, "admin_social_credentials_delete",
                actor_internal_user_id=actor.get("internal_user_id"),
                entity_type="social_provider", entity_id=network,
                after={"configured": False}, request=request,
            )
        return {"ok": True, "deleted": deleted}

    @router.post("/social/{network}/check-v2")
    async def check_social_credentials(network: str, request: Request) -> dict[str, Any]:
        actor = deps.require_admin(request)
        if network not in {"telegram", "vk", "instagram", "ok"}:
            raise HTTPException(404, "Социальная сеть не поддерживается.")
        saved = deps.saved_setting("social_syndication")
        networks = saved.get("networks") if isinstance(saved.get("networks"), dict) else {}
        config = networks.get(network) or {}
        try:
            result = await deps.probe_social(
                network,
                token=deps.secret_get(f"social_{network}_access_token"),
                target_id=str(config.get("targetId") or ""),
                application_key=str(config.get("applicationKey") or ""),
                session_secret=deps.secret_get("social_ok_session_secret") if network == "ok" else "",
            )
            config.update({"verified": True, "lastCheckedAt": utc_timestamp(), "lastError": None})
            status = 200
        except SocialProviderError as exc:
            result = None
            config.update({"verified": False, "lastCheckedAt": utc_timestamp(), "lastError": str(exc)})
            status = 502
        networks[network] = config
        saved["networks"] = networks
        deps.save_setting("social_syndication", saved)
        with deps.db() as conn:
            deps.record_audit(
                conn, "admin_social_connection_check",
                actor_internal_user_id=actor.get("internal_user_id"),
                entity_type="social_provider", entity_id=network,
                after={"ok": status == 200}, request=request,
            )
        if status != 200:
            raise HTTPException(status, str(config["lastError"]))
        return {"ok": True, "result": result}

    return router


def utc_timestamp() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
