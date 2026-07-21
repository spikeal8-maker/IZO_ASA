"""Admin bot router (ARCH-BE-BOTS-001, commit 2).

The 16 /api/admin/bots/* routes plus their admin-only helpers, extracted from
main.py behind a factory. This module never imports backend.main: every
main-defined collaborator is injected through the four frozen dependency
groups, and the worker runtime is passed explicitly. Provider configuration
stays canonical in main.py and is read through get_provider_config /
apply_runtime_config; no config is mirrored here. Secret access is limited to
injected callables (read/save/exists/delete); no raw secret store object is
held here, and tokens are never returned in responses.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import secrets as secrets_module
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

try:
    from ...services.bot_workers import BotRuntime
except ImportError:  # Direct `python backend/main.py` execution.
    from app.services.bot_workers import BotRuntime


# --- Request models (admin-bot-only; relocated with their only consumers) ---


class AdminBotTokenV2Request(BaseModel):
    token: str
    verify: bool = True


class AdminBotConfigV2Request(BaseModel):
    config: dict[str, Any]
    confirmModeChange: bool = False


class AdminBotWebhookActionV2Request(BaseModel):
    confirm: bool = False


# --- Dependency groups (four frozen bundles; no main / globals / locator) ---


@dataclass(frozen=True)
class BotAdminConfigOps:
    get_config: Callable[[], dict[str, Any]]
    save_config: Callable[[dict[str, Any]], dict[str, Any]]
    has_saved_config: Callable[[], bool]
    configured_webhook_url: Callable[[dict[str, Any], str], str]
    apply_runtime_config: Callable[[], dict[str, Any]]
    normalize_config: Callable[..., dict[str, Any]]
    is_production: Callable[[], bool]
    default_integrations: dict[str, Any]


@dataclass(frozen=True)
class BotAdminSecretOps:
    telegram_token: Callable[[], str]
    max_token: Callable[[], str]
    telegram_webhook_secret: Callable[[], str]
    max_webhook_secret: Callable[[], str]
    secret_source: Callable[[str, str], str]
    secret_updated_at: Callable[[str], str | None]
    save_secret: Callable[[str, str], None]
    secret_exists: Callable[[str], bool]
    secret_delete: Callable[[str], bool]
    secret_error: type[Exception] = Exception
    telegram_token_name: str = ""
    max_token_name: str = ""
    telegram_webhook_name: str = ""
    max_webhook_name: str = ""


@dataclass(frozen=True)
class BotAdminProviderOps:
    probe_telegram: Callable[..., Awaitable[Any]]
    probe_max: Callable[..., Awaitable[Any]]
    telegram_api: Callable[..., Awaitable[dict[str, Any]]]
    max_api: Callable[..., Awaitable[dict[str, Any]]]
    build_max_subscription: Callable[..., dict[str, Any]]
    validate_telegram_webhook_secret: Callable[[str, str], Any]
    validate_max_webhook_secret: Callable[[str, str], Any]
    safe_bot_error: Callable[[BaseException], str]
    # Full admin-status provider round-trips (probe + profile + webhook/subs
    # shaping), kept canonical in main and injected so they can be overridden
    # as a unit in tests without reaching the network.
    telegram_status_probe: Callable[[], Awaitable[dict[str, Any]]]
    max_status_probe: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
    public_https_status: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
    max_http_verify: Any = field(repr=False, default=True)


@dataclass(frozen=True)
class BotAdminInfrastructure:
    require_trusted_admin: Callable[[Request], dict[str, Any]]
    connect: Callable[[], Any]
    audit: Callable[..., Any]
    json_load: Callable[[Any], Any]


@dataclass(frozen=True)
class BotAdminDependencies:
    config: BotAdminConfigOps
    secret: BotAdminSecretOps
    provider: BotAdminProviderOps
    infra: BotAdminInfrastructure


def create_bots_admin_router(
    runtime: BotRuntime,
    dependencies: BotAdminDependencies,
) -> APIRouter:
    router = APIRouter()
    cfg = dependencies.config
    sec = dependencies.secret
    prov = dependencies.provider
    infra = dependencies.infra

    # --- admin-only helpers -------------------------------------------------

    def bot_diagnostics() -> dict[str, Any]:
        with infra.connect() as conn:
            row = conn.execute(
                "SELECT value_json FROM admin_settings WHERE key = 'bot_diagnostics'"
            ).fetchone()
        stored = infra.json_load(row["value_json"]) if row else {}
        return stored if isinstance(stored, dict) else {}

    def save_bot_diagnostic(provider: str, values: dict[str, Any]) -> dict[str, Any]:
        diagnostics = bot_diagnostics()
        current = diagnostics.get(provider)
        current = current if isinstance(current, dict) else {}
        diagnostics[provider] = {**current, **values}
        with infra.connect() as conn:
            conn.execute(
                "INSERT INTO admin_settings (key, value_json, updated_at) VALUES ('bot_diagnostics', ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                (
                    json.dumps(diagnostics, ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return diagnostics[provider]

    def config_readiness(
        provider: str,
        config: dict[str, Any],
        *,
        token_configured: bool,
        secret_configured: bool,
    ) -> dict[str, Any]:
        current = config[provider]
        mode = str(current.get("mode") or "disabled")
        target_webhook_url = cfg.configured_webhook_url(config, provider)
        polling_ready = token_configured and bool(current.get("pollingEnabled"))
        webhook_ready = (
            token_configured
            and secret_configured
            and target_webhook_url.startswith("https://")
        )
        runtime_cfg = runtime.provider_config(provider)
        return {
            "mode": mode,
            "pollingReady": polling_ready,
            "webhookReady": webhook_ready,
            "webhookUrl": target_webhook_url,
            "restartRequired": (
                mode != runtime_cfg.mode
                or bool(current.get("pollingEnabled")) != runtime_cfg.polling_enabled
            ),
        }

    def safe_config(config: dict[str, Any]) -> dict[str, Any]:
        return {
            "telegram": dict(config["telegram"]),
            "max": dict(config["max"]),
            "public": dict(config["public"]),
        }

    def record_audit(
        admin: dict[str, Any],
        request: Request,
        *,
        action: str,
        provider: str,
        ok: bool,
        details: dict[str, Any] | None = None,
    ) -> None:
        safe_details = {"provider": provider, "ok": bool(ok), **(details or {})}
        with infra.connect() as conn:
            infra.audit(
                conn,
                action,
                actor_internal_user_id=admin["internal_user_id"],
                entity_type="bot_integration",
                entity_id=provider,
                after=safe_details,
                request=request,
            )

    async def save_bot_token(provider: str, token: str, request: Request) -> dict[str, Any]:
        admin = infra.require_trusted_admin(request)
        secret_name = sec.telegram_token_name if provider == "telegram" else sec.max_token_name
        existed = sec.secret_exists(secret_name)
        try:
            sec.save_secret(secret_name, token.strip())
            if not cfg.has_saved_config():
                cfg.save_config(cfg.default_integrations)
            config = cfg.get_config()
            probe = (
                (await prov.probe_telegram(token=token.strip())).as_dict()
                if provider == "telegram"
                else (
                    await prov.probe_max(
                        token=token.strip(),
                        base_url=str(config["max"]["apiBaseUrl"]),
                        verify=prov.max_http_verify,
                    )
                ).as_dict()
            )
            checked_at = datetime.now(timezone.utc).isoformat()
            save_bot_diagnostic(
                provider,
                {
                    "checkedAt": checked_at,
                    "ok": bool(probe.get("ok")),
                    "status": probe.get("status"),
                    "error": None if probe.get("ok") else "Проверка подключения не пройдена.",
                },
            )
            record_audit(
                admin, request,
                action="admin_bot_token_replaced" if existed else "admin_bot_token_added",
                provider=provider, ok=True, details={"verified": bool(probe.get("ok"))},
            )
            return {
                "ok": True,
                "tokenConfigured": True,
                "tokenSource": sec.secret_source(
                    secret_name, "TELEGRAM_BOT_TOKEN" if provider == "telegram" else "MAX_BOT_TOKEN",
                ),
                "probe": probe,
                "activated": False,
            }
        except sec.secret_error as exc:
            record_audit(admin, request, action="admin_bot_token_save_failed", provider=provider, ok=False)
            raise HTTPException(503, "Защищённое хранилище недоступно.") from exc

    def delete_bot_token(provider: str, request: Request) -> dict[str, Any]:
        admin = infra.require_trusted_admin(request)
        name = sec.telegram_token_name if provider == "telegram" else sec.max_token_name
        try:
            deleted = sec.secret_delete(name)
        except sec.secret_error as exc:
            raise HTTPException(503, "Защищённое хранилище недоступно.") from exc
        record_audit(
            admin, request, action="admin_bot_token_deleted", provider=provider, ok=True,
            details={"deleted": deleted},
        )
        return {
            "ok": True,
            "deleted": deleted,
            "tokenConfigured": bool(sec.telegram_token() if provider == "telegram" else sec.max_token()),
            "source": sec.secret_source(
                name, "TELEGRAM_BOT_TOKEN" if provider == "telegram" else "MAX_BOT_TOKEN",
            ),
            "activated": False,
        }

    async def verify_bot(provider: str, request: Request) -> dict[str, Any]:
        admin = infra.require_trusted_admin(request)
        config = cfg.get_config()
        try:
            probe = (
                await prov.telegram_status_probe()
                if provider == "telegram"
                else await prov.max_status_probe(config)
            )
            checked_at = datetime.now(timezone.utc).isoformat()
            save_bot_diagnostic(
                provider,
                {
                    "checkedAt": checked_at,
                    "ok": bool(probe.get("ok")),
                    "status": probe.get("status"),
                    "error": None if probe.get("ok") else "Проверка подключения не пройдена.",
                },
            )
            record_audit(
                admin, request, action="admin_bot_connection_verified", provider=provider,
                ok=bool(probe.get("ok")), details={"status": probe.get("status")},
            )
            return {"ok": bool(probe.get("ok")), "checkedAt": checked_at, "probe": probe}
        except Exception as exc:
            message = prov.safe_bot_error(exc)
            save_bot_diagnostic(
                provider,
                {
                    "checkedAt": datetime.now(timezone.utc).isoformat(),
                    "ok": False, "status": "error", "error": message,
                },
            )
            record_audit(admin, request, action="admin_bot_connection_verified", provider=provider, ok=False)
            raise HTTPException(502, message) from exc

    def generate_webhook_secret(provider: str, request: Request) -> dict[str, Any]:
        admin = infra.require_trusted_admin(request)
        value = secrets_module.token_urlsafe(36)
        name = sec.telegram_webhook_name if provider == "telegram" else sec.max_webhook_name
        try:
            if provider == "telegram":
                prov.validate_telegram_webhook_secret("webhook", value)
            else:
                prov.validate_max_webhook_secret("webhook", value)
            sec.save_secret(name, value)
        except (RuntimeError, sec.secret_error) as exc:
            raise HTTPException(503, "Не удалось сохранить секрет webhook.") from exc
        record_audit(admin, request, action="admin_bot_webhook_secret_generated", provider=provider, ok=True)
        return {"ok": True, "configured": True, "source": "dpapi", "activated": False}

    # --- routes -------------------------------------------------------------

    @router.get("/api/admin/bots/config-v2")
    async def admin_bots_config_v2(request: Request) -> dict[str, Any]:
        infra.require_trusted_admin(request)
        config = cfg.get_config()
        telegram_cfg = runtime.provider_config("telegram")
        max_cfg = runtime.provider_config("max")
        return {
            "ok": True,
            "config": safe_config(config),
            "runtime": {
                "telegram": {"mode": telegram_cfg.mode, "pollingEnabled": telegram_cfg.polling_enabled},
                "max": {"mode": max_cfg.mode, "pollingEnabled": max_cfg.polling_enabled},
            },
            "restartNote": "Изменение режима применяется только после контролируемого перезапуска backend.",
        }

    @router.get("/api/admin/bots/status-v2")
    async def admin_bots_status_v2(request: Request) -> dict[str, Any]:
        infra.require_trusted_admin(request)
        config = cfg.get_config()
        telegram_token = sec.telegram_token()
        max_token = sec.max_token()
        telegram_secret = sec.telegram_webhook_secret()
        max_secret = sec.max_webhook_secret()
        telegram_probe_r, max_probe_r, public_status = await asyncio.gather(
            prov.telegram_status_probe(), prov.max_status_probe(config), prov.public_https_status(config),
        )
        diagnostics = bot_diagnostics()
        telegram_ready = config_readiness(
            "telegram", config, token_configured=bool(telegram_token), secret_configured=bool(telegram_secret),
        )
        max_ready = config_readiness(
            "max", config, token_configured=bool(max_token), secret_configured=bool(max_secret),
        )
        telegram_runtime = runtime.provider_config("telegram")
        max_runtime = runtime.provider_config("max")
        diag = runtime.max_polling_diag
        return {
            "ok": True,
            "telegram": {
                **telegram_ready,
                "tokenConfigured": bool(telegram_token),
                "tokenSource": sec.secret_source(sec.telegram_token_name, "TELEGRAM_BOT_TOKEN"),
                "tokenUpdatedAt": sec.secret_updated_at(sec.telegram_token_name),
                "webhookSecretConfigured": bool(telegram_secret),
                "webhookSecretSource": sec.secret_source(sec.telegram_webhook_name, "TELEGRAM_WEBHOOK_SECRET"),
                "webhookSecretUpdatedAt": sec.secret_updated_at(sec.telegram_webhook_name),
                "tokenValid": bool(telegram_probe_r.get("ok")),
                "probe": telegram_probe_r,
                "pollingActive": bool(
                    runtime.polling_tasks.get("telegram")
                    and not runtime.polling_tasks["telegram"].done()
                ),
                "runtimeMode": telegram_runtime.mode,
                "lastCheck": diagnostics.get("telegram"),
                "pollingHealth": runtime.polling_health.snapshot("telegram"),
                "commands": ["/start", "/app", "/help", "/gallery", "/settings"],
            },
            "max": {
                **max_ready,
                "tokenConfigured": bool(max_token),
                "tokenSource": sec.secret_source(sec.max_token_name, "MAX_BOT_TOKEN"),
                "tokenUpdatedAt": sec.secret_updated_at(sec.max_token_name),
                "webhookSecretConfigured": bool(max_secret),
                "webhookSecretSource": sec.secret_source(sec.max_webhook_name, "MAX_WEBHOOK_SECRET"),
                "webhookSecretUpdatedAt": sec.secret_updated_at(sec.max_webhook_name),
                "tokenValid": bool(max_probe_r.get("ok")),
                "probe": max_probe_r,
                "pollingActive": bool(
                    runtime.polling_tasks.get("max")
                    and not runtime.polling_tasks["max"].done()
                ),
                "runtimeMode": max_runtime.mode,
                "lastCheck": diagnostics.get("max"),
                "pollingHealth": runtime.polling_health.snapshot("max"),
                "subscriptionStatus": diag.get("subscriptionStatus"),
                "lastPollAt": diag.get("lastPollAt"),
                "lastPollError": diag.get("lastPollError"),
                "lastWebhookAt": diag.get("lastWebhookAt"),
                "lastWebhookError": diag.get("lastWebhookError"),
            },
            "public": public_status,
            "config": safe_config(config),
            "conflictWarning": (
                "Убедитесь, что этот бот отключён на старом сервере. Одновременный polling "
                "или переключение webhook может остановить получение сообщений действующим сервером."
            ),
        }

    @router.put("/api/admin/bots/config-v2")
    async def admin_bots_save_config_v2(req: AdminBotConfigV2Request, request: Request) -> dict[str, Any]:
        admin = infra.require_trusted_admin(request)
        before = cfg.get_config()
        try:
            normalized = cfg.normalize_config(req.config, production=cfg.is_production())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        changed_modes = [
            provider for provider in ("telegram", "max")
            if normalized[provider]["mode"] != before[provider]["mode"]
        ]
        if changed_modes and not req.confirmModeChange:
            raise HTTPException(409, "Изменение режима требует отдельного подтверждения администратора.")
        readiness = {
            "telegram": config_readiness(
                "telegram", normalized,
                token_configured=bool(sec.telegram_token()), secret_configured=bool(sec.telegram_webhook_secret()),
            ),
            "max": config_readiness(
                "max", normalized,
                token_configured=bool(sec.max_token()), secret_configured=bool(sec.max_webhook_secret()),
            ),
        }
        for provider in ("telegram", "max"):
            mode = normalized[provider]["mode"]
            if mode == "polling" and not readiness[provider]["pollingReady"]:
                raise HTTPException(400, f"{provider}: polling не готов — нужен токен и включение polling.")
            if mode == "webhook" and not readiness[provider]["webhookReady"]:
                raise HTTPException(400, f"{provider}: webhook не готов — нужны токен, секрет и публичный HTTPS.")
        saved = cfg.save_config(normalized)
        record_audit(
            admin, request, action="admin_bot_config_changed", provider="all", ok=True,
            details={"changedModes": changed_modes, "restartRequired": bool(changed_modes)},
        )
        return {"ok": True, "config": safe_config(saved), "restartRequired": bool(changed_modes), "activated": False}

    @router.put("/api/admin/bots/telegram/token-v2")
    async def admin_bots_telegram_token_v2(req: AdminBotTokenV2Request, request: Request) -> dict[str, Any]:
        return await save_bot_token("telegram", req.token, request)

    @router.put("/api/admin/bots/max/token-v2")
    async def admin_bots_max_token_v2(req: AdminBotTokenV2Request, request: Request) -> dict[str, Any]:
        return await save_bot_token("max", req.token, request)

    @router.delete("/api/admin/bots/telegram/token-v2")
    async def admin_bots_delete_telegram_token_v2(request: Request) -> dict[str, Any]:
        return delete_bot_token("telegram", request)

    @router.delete("/api/admin/bots/max/token-v2")
    async def admin_bots_delete_max_token_v2(request: Request) -> dict[str, Any]:
        return delete_bot_token("max", request)

    @router.post("/api/admin/bots/telegram/verify-v2")
    async def admin_bots_verify_telegram_v2(request: Request) -> dict[str, Any]:
        return await verify_bot("telegram", request)

    @router.post("/api/admin/bots/max/verify-v2")
    async def admin_bots_verify_max_v2(request: Request) -> dict[str, Any]:
        return await verify_bot("max", request)

    @router.post("/api/admin/bots/telegram/webhook-secret-v2")
    async def admin_bots_telegram_webhook_secret_v2(request: Request) -> dict[str, Any]:
        return generate_webhook_secret("telegram", request)

    @router.post("/api/admin/bots/max/webhook-secret-v2")
    async def admin_bots_max_webhook_secret_v2(request: Request) -> dict[str, Any]:
        return generate_webhook_secret("max", request)

    @router.post("/api/admin/bots/telegram/set-webhook-v2")
    async def admin_bots_set_telegram_webhook_v2(req: AdminBotWebhookActionV2Request, request: Request) -> dict[str, Any]:
        admin = infra.require_trusted_admin(request)
        if not req.confirm:
            raise HTTPException(409, "Подтвердите перенос Telegram webhook на этот сервер.")
        config = cfg.get_config()
        token = sec.telegram_token()
        secret = sec.telegram_webhook_secret()
        target = cfg.configured_webhook_url(config, "telegram")
        if not token or not secret or not target.startswith("https://"):
            raise HTTPException(400, "Telegram webhook не готов: нужны токен, секрет и публичный HTTPS.")
        try:
            result = await prov.telegram_api(
                token=token, method="setWebhook", payload={"url": target, "secret_token": secret},
            )
        except Exception as exc:
            record_audit(admin, request, action="admin_bot_webhook_set", provider="telegram", ok=False)
            raise HTTPException(502, prov.safe_bot_error(exc)) from exc
        record_audit(admin, request, action="admin_bot_webhook_set", provider="telegram", ok=True, details={"url": target})
        return {"ok": True, "webhookUrl": target, "providerResultOk": bool(result.get("ok"))}

    @router.post("/api/admin/bots/telegram/delete-webhook-v2")
    async def admin_bots_delete_telegram_webhook_v2(req: AdminBotWebhookActionV2Request, request: Request) -> dict[str, Any]:
        admin = infra.require_trusted_admin(request)
        if not req.confirm:
            raise HTTPException(409, "Подтвердите удаление Telegram webhook.")
        try:
            result = await prov.telegram_api(
                token=sec.telegram_token(), method="deleteWebhook", payload={"drop_pending_updates": False},
            )
        except Exception as exc:
            record_audit(admin, request, action="admin_bot_webhook_deleted", provider="telegram", ok=False)
            raise HTTPException(502, prov.safe_bot_error(exc)) from exc
        record_audit(admin, request, action="admin_bot_webhook_deleted", provider="telegram", ok=True)
        return {"ok": True, "providerResultOk": bool(result.get("ok"))}

    @router.post("/api/admin/bots/telegram/configure-v2")
    async def admin_bots_configure_telegram_v2(request: Request) -> dict[str, Any]:
        admin = infra.require_trusted_admin(request)
        commands = [
            {"command": "start", "description": "Открыть генератор"},
            {"command": "app", "description": "Открыть Mini App"},
            {"command": "help", "description": "Инструкция"},
            {"command": "gallery", "description": "Последние изображения"},
            {"command": "settings", "description": "Настройки"},
        ]
        try:
            result = await prov.telegram_api(
                token=sec.telegram_token(), method="setMyCommands", payload={"commands": commands},
            )
        except Exception as exc:
            record_audit(admin, request, action="admin_bot_commands_configured", provider="telegram", ok=False)
            raise HTTPException(502, prov.safe_bot_error(exc)) from exc
        record_audit(admin, request, action="admin_bot_commands_configured", provider="telegram", ok=True)
        return {"ok": bool(result.get("ok")), "commands": commands}

    @router.post("/api/admin/bots/max/set-webhook-v2")
    async def admin_bots_set_max_webhook_v2(req: AdminBotWebhookActionV2Request, request: Request) -> dict[str, Any]:
        admin = infra.require_trusted_admin(request)
        if not req.confirm:
            raise HTTPException(409, "Подтвердите перенос MAX webhook на этот сервер.")
        config = cfg.get_config()
        target = cfg.configured_webhook_url(config, "max")
        token = sec.max_token()
        secret = sec.max_webhook_secret()
        if not token or not secret or not target.startswith("https://"):
            raise HTTPException(400, "MAX webhook не готов: нужны токен, секрет и публичный HTTPS.")
        body = prov.build_max_subscription(target, secret, config["max"]["updateTypes"])
        try:
            result = await prov.max_api(
                token=token, base_url=config["max"]["apiBaseUrl"], verify=prov.max_http_verify,
                method="POST", path="/subscriptions", payload=body,
            )
        except Exception as exc:
            record_audit(admin, request, action="admin_bot_webhook_set", provider="max", ok=False)
            raise HTTPException(502, prov.safe_bot_error(exc)) from exc
        record_audit(admin, request, action="admin_bot_webhook_set", provider="max", ok=True, details={"url": target})
        return {"ok": True, "webhookUrl": target, "subscription": bool(result)}

    @router.post("/api/admin/bots/max/delete-webhook-v2")
    async def admin_bots_delete_max_webhook_v2(req: AdminBotWebhookActionV2Request, request: Request) -> dict[str, Any]:
        admin = infra.require_trusted_admin(request)
        if not req.confirm:
            raise HTTPException(409, "Подтвердите удаление MAX webhook.")
        config = cfg.get_config()
        target = cfg.configured_webhook_url(config, "max")
        try:
            result = await prov.max_api(
                token=sec.max_token(), base_url=config["max"]["apiBaseUrl"], verify=prov.max_http_verify,
                method="DELETE", path="/subscriptions", params={"url": target},
            )
        except Exception as exc:
            record_audit(admin, request, action="admin_bot_webhook_deleted", provider="max", ok=False)
            raise HTTPException(502, prov.safe_bot_error(exc)) from exc
        record_audit(admin, request, action="admin_bot_webhook_deleted", provider="max", ok=True)
        return {"ok": True, "subscription": bool(result)}

    return router
