"""Public bot and webhook router (ARCH-BE-BOTS-001, commit 3).

The 15 non-admin bot routes extracted from main.py behind a factory:
public platform/bot status, the local command preview, the Telegram/MAX
send/me/poll-once operator endpoints, the webhook setup operations, and the
Telegram and MAX webhook receivers.

This module never imports backend.main. The shared bot service layer
(telegram_api / max_api transports, poll-once, update runtimes and handlers)
stays canonical in main because it is also used by the polling workers,
gallery delivery and avatar caching; those operations are injected here through
explicit frozen dependency groups, late-bound so tests that swap them on main
are observed. Provider-agnostic webhook validators, payload builders and the
public status payloads are imported from their home modules under backend/app.
Only route-exclusive request models and the MAX webhook-subscription helper are
relocated with these routes. Paths, schemas, status codes and behaviour are
unchanged.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

try:  # package import in the running app; direct import under tools/tests.
    from ...services.bot_workers import BotRuntime
    from ...services.platform_status import (
        public_bots_status_payload,
        public_platforms_payload,
    )
    from ...services.max_updates import max_update_type
    from ...security.webhooks import (
        WebhookPayloadError,
        WebhookReplayGuard,
        build_telegram_set_webhook_payload,
        parse_webhook_json_object,
        validate_max_webhook_secret,
        validate_telegram_webhook_secret,
        webhook_secret_matches,
    )
except ImportError:  # Direct `python backend/main.py` execution.
    from app.services.bot_workers import BotRuntime
    from app.services.platform_status import (
        public_bots_status_payload,
        public_platforms_payload,
    )
    from app.services.max_updates import max_update_type
    from app.security.webhooks import (
        WebhookPayloadError,
        WebhookReplayGuard,
        build_telegram_set_webhook_payload,
        parse_webhook_json_object,
        validate_max_webhook_secret,
        validate_telegram_webhook_secret,
        webhook_secret_matches,
    )


# --- Route-exclusive request models (relocated with their only consumers) ---


class BotCommandRequest(BaseModel):
    platform: Literal["telegram", "max"]
    text: str = "/start"
    chatId: str | None = None


class BotSendMessageRequest(BaseModel):
    chatId: str | None = None
    userId: str | None = None
    text: str


# --- Route-exclusive webhook receiver limits (env-derived, per process) ------

TELEGRAM_WEBHOOK_MAX_BODY_BYTES = max(1024, min(1024 * 1024, int(os.getenv("TELEGRAM_WEBHOOK_MAX_BODY_BYTES", str(256 * 1024)))))
MAX_WEBHOOK_MAX_BODY_BYTES = max(1024, min(1024 * 1024, int(os.getenv("MAX_WEBHOOK_MAX_BODY_BYTES", str(256 * 1024)))))
TELEGRAM_WEBHOOK_REPLAY_CACHE_SIZE = max(128, min(100_000, int(os.getenv("TELEGRAM_WEBHOOK_REPLAY_CACHE_SIZE", "4096"))))
_telegram_webhook_replay_guard = WebhookReplayGuard(TELEGRAM_WEBHOOK_REPLAY_CACHE_SIZE)


# --- Dependency groups (shared main collaborators; no main import here) -------


@dataclass(frozen=True)
class BotPublicTransport:
    telegram_api: Callable[..., Awaitable[dict[str, Any]]]
    max_api: Callable[..., Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class BotPublicMessaging:
    telegram_poll_once: Callable[..., Awaitable[dict[str, Any]]]
    max_poll_once: Callable[..., Awaitable[dict[str, Any]]]
    handle_telegram_update: Callable[..., Awaitable[Any]]
    handle_max_update: Callable[..., Awaitable[Any]]
    bot_command_response: Callable[[str, str], dict[str, Any]]
    pending_max_login_count: Callable[[], int]
    # MAX webhook subscription mutates worker-shared diag and is exercised
    # directly in tests, so it stays canonical in main and is injected here.
    configure_max_webhook: Callable[[], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class BotPublicConfig:
    require_trusted_admin: Callable[[Request], Any]
    telegram_webhook_secret: Callable[[], str]
    max_webhook_secret: Callable[[], str]
    bot_updates_mode: Callable[[], str]
    max_updates_mode: Callable[[], str]


@dataclass(frozen=True)
class BotPublicDependencies:
    transport: BotPublicTransport
    messaging: BotPublicMessaging
    config: BotPublicConfig


def create_bots_public_router(
    runtime: BotRuntime,
    dependencies: BotPublicDependencies,
) -> APIRouter:
    router = APIRouter()
    t = dependencies.transport
    m = dependencies.messaging
    c = dependencies.config

    # --- public capability endpoints -----------------------------------------

    @router.get("/api/platforms")
    async def platforms() -> dict[str, Any]:
        # Product capability only; operator diagnostics stay admin-only.
        return public_platforms_payload()

    @router.get("/api/bots/status")
    async def bots_status() -> dict[str, Any]:
        return public_bots_status_payload()

    @router.post("/api/bots/local-command")
    async def bots_local_command(req: BotCommandRequest) -> dict[str, Any]:
        response = m.bot_command_response(req.platform, req.text)
        response["chatId"] = req.chatId
        response["delivery"] = "local"
        return response

    # --- Telegram operator endpoints -----------------------------------------

    @router.post("/api/telegram/send-message")
    async def telegram_send_message(req: BotSendMessageRequest, request: Request) -> dict[str, Any]:
        c.require_trusted_admin(request)
        if not req.chatId:
            raise HTTPException(400, "chatId is required for Telegram sendMessage.")
        return await t.telegram_api("sendMessage", {"chat_id": req.chatId, "text": req.text})

    @router.get("/api/telegram/me")
    async def telegram_me(request: Request) -> dict[str, Any]:
        c.require_trusted_admin(request)
        return await t.telegram_api("getMe")

    @router.post("/api/telegram/poll-once")
    async def telegram_poll_once(request: Request) -> dict[str, Any]:
        c.require_trusted_admin(request)
        return await m.telegram_poll_once(timeout=0, limit=10)

    @router.post("/api/telegram/set-webhook")
    async def telegram_set_webhook(request: Request) -> dict[str, Any]:
        c.require_trusted_admin(request)
        public_url = os.getenv("BACKEND_PUBLIC_URL", "")
        if not public_url.startswith("https://"):
            raise HTTPException(400, "BACKEND_PUBLIC_URL must be an HTTPS URL for Telegram webhook mode.")
        try:
            validate_telegram_webhook_secret("webhook", c.telegram_webhook_secret())
        except RuntimeError as exc:
            raise HTTPException(400, str(exc)) from exc
        return await t.telegram_api(
            "setWebhook",
            build_telegram_set_webhook_payload(public_url, c.telegram_webhook_secret()),
        )

    @router.post("/api/telegram/configure-bot")
    async def telegram_configure_bot(request: Request) -> dict[str, Any]:
        c.require_trusted_admin(request)
        commands = [
            {"command": "start", "description": "Открыть генератор"},
            {"command": "app", "description": "Открыть Mini App"},
            {"command": "help", "description": "Инструкция"},
            {"command": "gallery", "description": "Последние изображения"},
            {"command": "settings", "description": "Настройки"},
        ]
        result: dict[str, Any] = {"commands": await t.telegram_api("setMyCommands", {"commands": commands})}
        app_url = os.getenv("APP_PUBLIC_URL", "")
        if app_url.startswith("https://"):
            result["menuButton"] = await t.telegram_api(
                "setChatMenuButton",
                {"menu_button": {"type": "web_app", "text": "Открыть генератор", "web_app": {"url": app_url}}},
            )
        else:
            result["menuButton"] = {"ok": False, "reason": "APP_PUBLIC_URL must be HTTPS for Telegram Mini App menu button."}
        return result

    @router.post("/api/telegram/delete-webhook")
    async def telegram_delete_webhook(request: Request) -> dict[str, Any]:
        c.require_trusted_admin(request)
        return await t.telegram_api("deleteWebhook", {"drop_pending_updates": False})

    # --- MAX operator endpoints ----------------------------------------------

    @router.post("/api/max/send-message")
    async def max_send_message(req: BotSendMessageRequest, request: Request) -> dict[str, Any]:
        c.require_trusted_admin(request)
        if not req.chatId and not req.userId:
            raise HTTPException(400, "chatId or userId is required for MAX messages.")
        params: dict[str, Any] = {}
        if req.chatId:
            params["chat_id"] = req.chatId
        if req.userId:
            params["user_id"] = req.userId
        return await t.max_api("POST", "/messages", {"text": req.text}, params=params)

    @router.get("/api/max/me")
    async def max_me(request: Request) -> dict[str, Any]:
        c.require_trusted_admin(request)
        return await t.max_api("GET", "/me")

    @router.post("/api/max/poll-once")
    async def max_poll_once(request: Request) -> dict[str, Any]:
        c.require_trusted_admin(request)
        if m.pending_max_login_count() > 0:
            raise HTTPException(409, "active_max_login_challenge")
        return await m.max_poll_once(timeout=0, limit=10)

    @router.post("/api/max/set-webhook")
    async def max_set_webhook(request: Request) -> dict[str, Any]:
        c.require_trusted_admin(request)
        try:
            return await m.configure_max_webhook()
        except RuntimeError as exc:
            raise HTTPException(400, str(exc)) from exc

    # --- webhook receivers ----------------------------------------------------

    @router.post("/api/telegram/webhook")
    async def telegram_webhook(request: Request) -> dict[str, Any]:
        if c.bot_updates_mode() != "webhook":
            raise HTTPException(404, "Telegram webhook receiver is disabled.")
        try:
            validate_telegram_webhook_secret(c.bot_updates_mode(), c.telegram_webhook_secret())
        except RuntimeError as exc:
            raise HTTPException(503, "Telegram webhook is not configured.") from exc
        provided_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if not webhook_secret_matches(c.telegram_webhook_secret(), provided_secret):
            raise HTTPException(403, "Invalid Telegram webhook secret.")
        content_length = request.headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > TELEGRAM_WEBHOOK_MAX_BODY_BYTES:
                    raise HTTPException(413, "Telegram webhook body is too large.")
            except ValueError:
                pass
        try:
            payload = parse_webhook_json_object(
                await request.body(),
                TELEGRAM_WEBHOOK_MAX_BODY_BYTES,
                provider_name="Telegram",
            )
        except WebhookPayloadError as exc:
            raise HTTPException(exc.status_code, exc.message) from exc
        if not _telegram_webhook_replay_guard.claim(payload.get("update_id")):
            return {"ok": True, "duplicate": True}
        try:
            await m.handle_telegram_update(payload, send_replies=True)
        except Exception as exc:
            _telegram_webhook_replay_guard.release(payload.get("update_id"))
            print("telegram webhook handler error", type(exc).__name__)
            raise HTTPException(503, "Telegram webhook processing failed.") from exc
        return {"ok": True}

    @router.post("/api/max/webhook")
    async def max_webhook(request: Request) -> dict[str, Any]:
        if c.max_updates_mode() != "webhook":
            raise HTTPException(404, "MAX webhook receiver is disabled.")
        try:
            validate_max_webhook_secret(c.max_updates_mode(), c.max_webhook_secret())
        except RuntimeError as exc:
            raise HTTPException(503, "MAX webhook is not configured.") from exc
        if not webhook_secret_matches(c.max_webhook_secret(), request.headers.get("X-Max-Bot-Api-Secret")):
            raise HTTPException(403, "Invalid MAX webhook secret.")
        content_length = request.headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > MAX_WEBHOOK_MAX_BODY_BYTES:
                    raise HTTPException(413, "MAX webhook body is too large.")
            except ValueError:
                pass
        try:
            payload = parse_webhook_json_object(
                await request.body(),
                MAX_WEBHOOK_MAX_BODY_BYTES,
                provider_name="MAX",
            )
        except WebhookPayloadError as exc:
            raise HTTPException(exc.status_code, exc.message) from exc
        runtime.max_polling_diag["lastWebhookAt"] = datetime.now(timezone.utc).isoformat()
        runtime.max_polling_diag["lastWebhookError"] = None
        print(f"MAX webhook update received type={max_update_type(payload)}")
        try:
            await m.handle_max_update(payload, send_replies=True)
        except Exception as exc:
            runtime.max_polling_diag["lastWebhookError"] = type(exc).__name__
            print("max webhook handler error", type(exc).__name__)
            raise HTTPException(503, "MAX webhook processing failed.") from exc
        return {"ok": True}

    return router
