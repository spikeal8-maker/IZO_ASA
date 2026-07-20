"""Public, product-safe status payloads for anonymous API consumers.

SEC-DIAG-001: the anonymous `/api/platforms` and `/api/bots/status` endpoints
must expose only product capability data. Operator diagnostics (token
presence, webhook/TLS state, internal URLs, database location, polling
health) live exclusively in `/api/admin/bots/status-v2` behind
`require_trusted_admin`.
"""
from __future__ import annotations

import os
from typing import Any

BOT_COMMANDS: tuple[str, ...] = ("/start", "/app", "/help", "/gallery", "/settings")
BOT_BUTTON_TEXT = "Открыть генератор"


def mini_app_public_url(platform: str = "web") -> str:
    base = os.getenv("APP_PUBLIC_URL", "http://127.0.0.1:5173")
    return f"{base}?platform={platform}"


def public_platforms_payload() -> dict[str, Any]:
    return {
        "web": {"ready": True, "url": mini_app_public_url("web")},
        "telegram": {
            "ready": True,
            "url": mini_app_public_url("telegram"),
            "commands": list(BOT_COMMANDS),
            "buttonText": BOT_BUTTON_TEXT,
        },
        "max": {
            "ready": True,
            "url": mini_app_public_url("max"),
            "commands": list(BOT_COMMANDS),
            "buttonText": BOT_BUTTON_TEXT,
        },
    }


def public_bots_status_payload() -> dict[str, Any]:
    return {
        "ok": True,
        "platforms": {
            "telegram": {
                "ready": True,
                "commands": list(BOT_COMMANDS),
                "buttonText": BOT_BUTTON_TEXT,
            },
            "max": {
                "ready": True,
                "commands": list(BOT_COMMANDS),
                "buttonText": BOT_BUTTON_TEXT,
            },
        },
    }
