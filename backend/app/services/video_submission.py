"""Idempotent guards for expensive asynchronous video submissions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any


ACTIVE_STATUSES = ("submitting", "queued", "pending", "in_progress", "finalizing")
UNKNOWN_RETRY_COOLDOWN_SECONDS = 15 * 60


class DuplicateVideoSubmission(RuntimeError):
    """An identical expensive provider request is already in flight."""


def request_fingerprint(request: Any) -> str:
    """Return a stable digest without persisting prompts or source data twice."""

    source = {
        "mode": getattr(request, "mode", None),
        "model": getattr(request, "model", None),
        "prompt": str(getattr(request, "prompt", "") or "").strip(),
        "duration": getattr(request, "duration", None),
        "resolution": getattr(request, "resolution", None),
        "aspectRatio": getattr(request, "aspectRatio", None),
        "generateAudio": bool(getattr(request, "generateAudio", False)),
        "firstFrame": getattr(request, "firstFrame", None),
        "lastFrame": getattr(request, "lastFrame", None),
        "references": list(getattr(request, "references", None) or []),
    }
    encoded = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def blocking_duplicate(conn: Any, user_id: str, fingerprint: str, *, now: datetime | None = None) -> Any | None:
    """Find an active or recently uncertain identical provider submission."""

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    earliest = (current - timedelta(hours=6)).isoformat()
    rows = conn.execute(
        "SELECT id,status,settings_json,created_at FROM jobs WHERE user_id=? AND provider='openrouter' "
        "AND mode IN ('text_to_video','image_to_video','first_last_frame','reference_to_video') "
        "AND created_at>=? ORDER BY created_at DESC LIMIT 50",
        (user_id, earliest),
    ).fetchall()
    for row in rows:
        try:
            settings = json.loads(row["settings_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(settings, dict) or settings.get("submissionFingerprint") != fingerprint:
            continue
        status = str(row["status"] or "")
        if status in ACTIVE_STATUSES:
            return row
        if settings.get("openrouterSubmissionState") == "provider_response_timeout":
            try:
                created_at = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                return row
            if current - created_at.astimezone(timezone.utc) < timedelta(seconds=UNKNOWN_RETRY_COOLDOWN_SECONDS):
                return row
    return None
