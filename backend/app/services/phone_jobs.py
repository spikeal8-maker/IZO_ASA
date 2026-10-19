"""Provider-neutral Phone job snapshots and durable recovery queries."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol

from .generation_jobs import public_generation_error_message
from .video_presentation import public_video_error_message


TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "expired"})
PUBLIC_STATES = frozenset({"created", "queued", "running", "processing", *TERMINAL_STATES})
VIDEO_MODES = frozenset({"text_to_video", "image_to_video", "first_last_frame", "reference_to_video"})
AUDIO_MODES = frozenset({"text_to_speech", "speech_to_text"})
THREE_D_MODES = frozenset({"text_to_3d", "image_to_3d", "refine_3d", "texture_3d"})


class PhoneJobConnection(Protocol):
    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> Any: ...


def _value(source: Mapping[str, Any] | Any, key: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(key, default)
    try:
        return source[key]
    except (KeyError, IndexError, TypeError):
        return default


def _settings(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def phone_job_modality(mode: Any) -> str:
    normalized = str(mode or "").strip().casefold()
    if normalized in VIDEO_MODES:
        return "video"
    if normalized in AUDIO_MODES:
        return "audio"
    if normalized in THREE_D_MODES:
        return "3d"
    if normalized == "chat":
        return "chat"
    return "image"


def _progress(value: Any) -> int:
    try:
        return max(0, min(100, int(float(value or 0))))
    except (TypeError, ValueError):
        return 0


def normalize_phone_job(payload: Mapping[str, Any], *, modality: str | None = None) -> dict[str, Any]:
    status = str(_value(payload, "status", "queued") or "queued").casefold()
    status = {"sent_to_comfyui": "running", "sent_to_openrouter": "running", "uploading": "processing"}.get(status, status)
    if status not in PUBLIC_STATES:
        status = "created"
    if status == "processing":
        phase = "processing"
    elif status == "running":
        phase = "running"
    elif status == "queued":
        phase = "queued"
    else:
        phase = "terminal" if status in TERMINAL_STATES else "created"
    resolved_modality = modality or phone_job_modality(_value(payload, "mode"))
    error = _value(payload, "error") or _value(payload, "error_message")
    result_url = _value(payload, "resultUrl") or _value(payload, "videoUrl")
    result_id = _value(payload, "resultImageId") or _value(payload, "galleryVideoId")
    asset = None
    if result_url:
        asset = {
            "id": result_id,
            "type": resolved_modality,
            "url": result_url,
            "thumbnailUrl": _value(payload, "thumbnailUrl") or _value(payload, "posterUrl"),
            "width": _value(payload, "width"),
            "height": _value(payload, "height"),
            "durationSeconds": _value(payload, "duration") or _value(payload, "durationSeconds"),
            "aspectRatio": _value(payload, "aspectRatio"),
        }
    return {
        "id": str(_value(payload, "id") or ""),
        "modality": resolved_modality,
        "operation": str(_value(payload, "mode") or ""),
        "status": status,
        "phase": phase,
        "progress": _progress(_value(payload, "progress", 0)),
        "message": public_generation_error_message(error) if error else str(_value(payload, "message") or ""),
        "createdAt": _value(payload, "createdAt") or _value(payload, "created_at"),
        "startedAt": _value(payload, "startedAt") or _value(payload, "started_at"),
        "completedAt": _value(payload, "completedAt") or _value(payload, "completed_at"),
        "terminal": status in TERMINAL_STATES,
        "result": asset,
        "billing": {
            "chargedTokens": _value(payload, "tokenCost") or _value(payload, "chargedTokens"),
            "tokenKind": _value(payload, "tokenKind"),
            "refunded": bool(_value(payload, "refunded", False)),
        },
    }


def list_phone_jobs(
    conn: PhoneJobConnection,
    user_id: str,
    *,
    active_only: bool = True,
    limit: int = 30,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 60))
    where = "AND status NOT IN ('completed','failed','cancelled','expired')" if active_only else ""
    rows = conn.execute(
        f"SELECT * FROM jobs WHERE user_id=? {where} ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    output: list[dict[str, Any]] = []
    for row in rows:
        settings = _settings(_value(row, "settings_json"))
        mode = _value(row, "mode")
        modality = phone_job_modality(mode)
        payload = {
            "id": _value(row, "id"),
            "mode": mode,
            "status": _value(row, "status"),
            "progress": _value(row, "progress"),
            "error_message": _value(row, "error_message"),
            "created_at": _value(row, "created_at"),
            "started_at": _value(row, "started_at"),
            "completed_at": _value(row, "completed_at"),
            "tokenCost": settings.get("tokenCost"),
        }
        if modality == "video" and _value(row, "provider") == "local_ltx":
            payload["error_message"] = public_video_error_message(payload["error_message"], provider="local_ltx")
        if modality == "video" and settings.get("localFile"):
            payload.update(
                videoUrl=f"/api/video/media/{_value(row, 'id')}",
                galleryVideoId=settings.get("galleryVideoId"),
                duration=settings.get("duration"),
                aspectRatio=settings.get("aspectRatio"),
            )
        elif modality == "image":
            image = conn.execute(
                "SELECT id,url,thumbnail_url,width,height FROM images WHERE job_id=? AND user_id=? AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 1",
                (str(_value(row, "id")), user_id),
            ).fetchone()
            if image is not None:
                payload.update(
                    resultImageId=_value(image, "id"), resultUrl=_value(image, "url"),
                    thumbnailUrl=_value(image, "thumbnail_url"), width=_value(image, "width"),
                    height=_value(image, "height"),
                )
        output.append(normalize_phone_job(payload, modality=modality))
    return output
