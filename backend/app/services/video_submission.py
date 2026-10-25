"""Idempotent guards for expensive asynchronous video submissions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any


ACTIVE_STATUSES = ("submitting", "queued", "pending", "in_progress", "finalizing")


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
    """Block an active or unreconciled ambiguous paid video dispatch.

    The previous 15-minute cooldown and 50-row/six-hour limit allowed a second
    provider call while the original timeout could already have been accepted.
    Retain the fail-closed guard until authoritative reconciliation updates the
    stored submission state, even if the original request is old or failed.
    The optional now argument remains for existing callers/tests.
    """
    rows = conn.execute(
        "SELECT id,status,settings_json,created_at FROM jobs WHERE user_id=? AND provider='openrouter' "
        "AND mode IN ('text_to_video','image_to_video','first_last_frame','reference_to_video') "
        "AND (status IN ('submitting','queued','pending','in_progress','finalizing') "
        "OR settings_json LIKE '%provider_response_timeout%') "
        "ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    for row in rows:
        try:
            settings = json.loads(row["settings_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            if "provider_response_timeout" in str(row["settings_json"] or ""):
                # Do not silently discard an ambiguous financial receipt.
                raise DuplicateVideoSubmission("Unreconciled video provider outcome has invalid metadata.") from None
            continue
        if not isinstance(settings, dict) or settings.get("submissionFingerprint") != fingerprint:
            continue
        status = str(row["status"] or "")
        if status in ACTIVE_STATUSES:
            return row
        if status != "completed" and settings.get("openrouterSubmissionState") == "provider_response_timeout":
            return row
    return None
