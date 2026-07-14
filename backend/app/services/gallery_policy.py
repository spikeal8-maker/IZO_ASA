"""Pure gallery quota and eviction policy."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def normalize_gallery_plan(
    value: Any,
    allowed_plans: Sequence[str],
    *,
    fallback: str = "mini",
) -> str:
    """Return the legacy normalized tariff name or its configured fallback."""
    plan = str(value or fallback).lower()
    return plan if plan in allowed_plans else fallback


def build_gallery_quota(
    *,
    plan: str,
    tariff: Mapping[str, Any],
    gallery_used: int,
) -> dict[str, Any]:
    """Build the public gallery quota payload without database dependencies."""
    total = int(tariff["gallery_slots"])
    used = int(gallery_used)
    return {
        "plan": plan,
        "daily_tokens": int(tariff["daily_tokens"]),
        "openrouter_monthly_tokens": int(tariff.get("openrouter_monthly_tokens") or 0),
        "gallery_slots": total,
        "video_enabled": bool(tariff.get("video_enabled")),
        "video_slots": int(tariff.get("video_slots") or 0),
        "gallery_used": used,
        "gallery_free": max(0, total - used),
        "gallery_full": used >= total,
    }


def gallery_eviction_target(quota: Mapping[str, Any]) -> int:
    """Return how many oldest unprotected rows must make room for a new image."""
    total = int(quota.get("gallery_slots") or 0)
    used = int(quota.get("gallery_used") or 0)
    if total <= 0 or used < total:
        return 0
    return 2 if used > total else 1
