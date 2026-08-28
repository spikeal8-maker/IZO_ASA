"""Product-safe manifest for the native mobile application shell."""

from __future__ import annotations

import os
from typing import Any


PHONE_API_VERSION = "v1"
PHONE_DEFAULT_ROUTE = "/phone/image"


def _enabled(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


def phone_platform_manifest() -> dict[str, Any]:
    """Return UI capabilities without provider, checkpoint, or cost internals."""

    workspaces = [
        {
            "id": "image",
            "label": "Картинка",
            "shortLabel": "Фото",
            "route": "/phone/image",
            "enabled": _enabled("PHONE_IMAGE_ENABLED", True),
            "stage": "ready",
            "operations": ["create", "edit", "compose", "draw"],
            "navigation": "primary",
        },
        {
            "id": "video",
            "label": "Видео",
            "shortLabel": "Видео",
            "route": "/phone/video",
            "enabled": _enabled("PHONE_VIDEO_ENABLED", True),
            "stage": "ready",
            "operations": ["text_to_video", "image_to_video", "references"],
            "navigation": "primary",
        },
        {
            "id": "chat",
            "label": "Чат",
            "shortLabel": "Чат",
            "route": "/phone/chat",
            "enabled": _enabled("PHONE_CHAT_ENABLED", True),
            "stage": "ready",
            "operations": ["conversation", "web_search", "generate_image"],
            "navigation": "primary",
        },
        {
            "id": "audio",
            "label": "Звук",
            "shortLabel": "Звук",
            "route": "/phone/audio",
            "enabled": _enabled("PHONE_AUDIO_ENABLED", True),
            "stage": "partial",
            "operations": ["speech_to_text"],
            "navigation": "primary",
        },
    ]
    return {
        "ok": True,
        "apiVersion": PHONE_API_VERSION,
        "defaultRoute": PHONE_DEFAULT_ROUTE,
        "shell": {
            "nativeReact": True,
            "resumeJobs": True,
            "offlineDrafts": True,
            "notificationHost": True,
        },
        "contracts": {
            "capabilities": PHONE_API_VERSION,
            "jobs": PHONE_API_VERSION,
            "media": PHONE_API_VERSION,
            "billing": PHONE_API_VERSION,
        },
        "workspaces": workspaces,
    }
