"""Generation job persistence and persisted API-response mapping."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from typing import Any, Protocol


PERSISTED_JOB_SETTINGS_KEYS = (
    "tokenCost",
    "resultUrl",
    "width",
    "height",
    "gallerySaveStatus",
    "galleryQuota",
    "openrouterRequest",
    "openrouterModel",
    "openrouterResponseId",
    "openrouterUsage",
    "openrouterCostUsd",
    "openrouterBilling",
    "tokenAdjustment",
)

COMPACTABLE_JOB_STATUSES = frozenset({"completed"})

PUBLIC_SERVER_ERROR = (
    "Не удалось завершить генерацию из-за временного сбоя. "
    "Попробуйте ещё раз позже или обратитесь в поддержку."
)
_PRIVATE_ERROR_DETAILS = re.compile(
    r"openai|openrouter|comfy\s*ui|coffee\s*ui|api[\s_-]*key|provider|endpoint|traceback|stack trace|"
    r"insufficient[_\s-]*(?:credits?|quota)|billing|authentication failed|connection refused|econnrefused",
    re.IGNORECASE,
)


def public_generation_error_message(value: Any) -> str:
    """Keep provider diagnostics in storage while returning a neutral user message."""
    message = str(value or "").strip()
    if not message or _PRIVATE_ERROR_DETAILS.search(message):
        return PUBLIC_SERVER_ERROR
    return message


def _compact_terminal_media(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _compact_terminal_media(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_compact_terminal_media(item) for item in value]
    if isinstance(value, str) and value.startswith("data:image") and "," in value:
        header, payload = value.split(",", 1)
        mime_type = header[5:].split(";", 1)[0] or "image/unknown"
        approximate_bytes = max(0, len(payload) * 3 // 4)
        return f"[data-image-omitted:{mime_type}:{approximate_bytes}]"
    return value


class JobConnection(Protocol):
    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> Any: ...


def _row_get(row: Mapping[str, Any] | Any | None, key: str) -> Any:
    if row is None:
        return None
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def _safe_json_load(text: str | None) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def job_response_from_row(
    row: Mapping[str, Any] | Any,
    image_row: Mapping[str, Any] | Any | None = None,
    *,
    model_display_name: Callable[[Any], str],
) -> dict[str, Any]:
    settings = _safe_json_load(row["settings_json"]) or {}
    result_url = _row_get(image_row, "url") or settings.get("resultUrl")
    public_error = public_generation_error_message(row["error_message"]) if row["error_message"] else None
    response: dict[str, Any] = {
        "id": row["id"],
        "userId": row["user_id"],
        "mode": row["mode"],
        "provider": row["provider"],
        "status": row["status"],
        "progress": row["progress"],
        "message": public_error or ("Готово" if row["status"] == "completed" else row["status"]),
        "resultImageId": row["result_image_id"],
        "resultUrl": result_url,
        "thumbnailUrl": _row_get(image_row, "thumbnail_url"),
        "width": _row_get(image_row, "width") or settings.get("width"),
        "height": _row_get(image_row, "height") or settings.get("height"),
        "createdAt": row["created_at"],
        "completedAt": row["completed_at"],
        "tokenCost": settings.get("tokenCost"),
        "openrouterBilling": settings.get("openrouterBilling")
        if isinstance(settings.get("openrouterBilling"), dict)
        else None,
    }
    if row["error_message"]:
        response["error"] = public_error
    if image_row is not None:
        image_settings = _safe_json_load(_row_get(image_row, "settings_json")) or {}
        response.update(
            {
                "width": _row_get(image_row, "width"),
                "height": _row_get(image_row, "height"),
                "modelProfile": model_display_name(
                    image_settings.get("modelProfile") or settings.get("modelProfile") or row["provider"]
                ),
                "generationTimeMs": image_settings.get("generationTimeMs"),
            }
        )
    return response


def get_persisted_job_response(
    conn: JobConnection,
    job_id: str,
    user_id: str,
    *,
    model_display_name: Callable[[Any], str],
) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ? AND user_id = ?", (job_id, user_id)).fetchone()
    if row is None:
        return None
    image_row = None
    if row["result_image_id"]:
        image_row = conn.execute(
            "SELECT * FROM images WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
            (row["result_image_id"], user_id),
        ).fetchone()
    if image_row is None:
        image_row = conn.execute(
            """
            SELECT * FROM images
            WHERE job_id = ? AND user_id = ? AND deleted_at IS NULL
            ORDER BY created_at DESC LIMIT 1
            """,
            (job_id, user_id),
        ).fetchone()
    return job_response_from_row(row, image_row, model_display_name=model_display_name)


def persist_job(
    conn: JobConnection,
    job: dict[str, Any],
    *,
    request_data: dict[str, Any],
    request_mode: str,
    request_provider: str,
    request_prompt: str,
    now_iso: str,
) -> None:
    settings = request_data
    for key in PERSISTED_JOB_SETTINGS_KEYS:
        if key in job:
            settings[key] = job.get(key)
    if str(job.get("status") or "").lower() in COMPACTABLE_JOB_STATUSES:
        settings = _compact_terminal_media(dict(settings))
    conn.execute(
        """
        INSERT INTO jobs (id, user_id, mode, provider, status, progress, prompt_original, prompt_translated,
                          result_image_id, error_message, settings_json, created_at, started_at, completed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            status=excluded.status,
            progress=excluded.progress,
            result_image_id=excluded.result_image_id,
            error_message=excluded.error_message,
            settings_json=excluded.settings_json,
            completed_at=excluded.completed_at
        """,
        (
            job["id"],
            job.get("userId", "demo_user"),
            job.get("mode", request_mode),
            job.get("provider", request_provider),
            job.get("status", "queued"),
            int(job.get("progress", 0)),
            request_prompt or "",
            "",
            job.get("resultImageId"),
            job.get("error"),
            json.dumps(settings, ensure_ascii=False),
            job.get("createdAt") or now_iso,
            job.get("startedAt"),
            job.get("completedAt"),
        ),
    )
