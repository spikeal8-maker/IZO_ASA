"""Read-only dashboard time series and payment summaries; fixed Moscow business-day rules."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any


MOSCOW = timezone(timedelta(hours=3), name="Europe/Moscow")
IMAGE_JOB_MODES = {
    "text_to_image", "image_to_image", "edit", "paint", "inpaint",
    "outpaint", "faceswap", "remove_background",
}
VIDEO_JOB_MODES = {
    "text_to_video", "image_to_video", "first_last_frame", "reference_to_video",
}


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _generation_kind(mode: str | None, provider: str | None) -> str | None:
    normalized_mode = str(mode or "")
    if normalized_mode in VIDEO_JOB_MODES:
        return "videos"
    if normalized_mode not in IMAGE_JOB_MODES:
        return None
    return "local_images" if str(provider or "") == "comfyui" else "paid_images"


def dashboard_generation_timeline(
    conn: sqlite3.Connection,
    *,
    days: int = 90,
    now: datetime | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Build dashboard image/video series from one bounded jobs query."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    daily_keys = [
        (current.date() - timedelta(days=offset)).isoformat()
        for offset in range(days - 1, -1, -1)
    ]
    categories = ("local_images", "paid_images", "videos")
    daily = {category: {key: 0 for key in daily_keys} for category in categories}
    rolling_specs = {
        "1h": (60, 5),
        "6h": (360, 30),
        "12h": (720, 60),
        "24h": (1440, 60),
    }
    rolling: dict[str, dict[str, dict[str, int]]] = {category: {} for category in categories}
    rolling_starts: dict[str, datetime] = {}
    for suffix, (minutes, bucket_minutes) in rolling_specs.items():
        end_bucket = current.replace(
            minute=(current.minute // bucket_minutes) * bucket_minutes,
            second=0,
            microsecond=0,
        )
        bucket_count = max(1, (minutes + bucket_minutes - 1) // bucket_minutes)
        buckets = [
            end_bucket - timedelta(minutes=bucket_minutes * offset)
            for offset in range(bucket_count - 1, -1, -1)
        ]
        rolling_starts[suffix] = buckets[0]
        for category in categories:
            rolling[category][suffix] = {bucket.isoformat(): 0 for bucket in buckets}

    query_start = min(
        datetime.combine(current.date() - timedelta(days=days - 1), datetime.min.time(), timezone.utc),
        min(rolling_starts.values()),
    )
    rows = conn.execute(
        "SELECT created_at, mode, provider FROM jobs WHERE created_at >= ? ORDER BY created_at",
        (query_start.isoformat(),),
    ).fetchall()
    for row in rows:
        created_at = _parse_utc(row["created_at"])
        category = _generation_kind(row["mode"], row["provider"])
        if created_at is None or created_at > current or category is None:
            continue
        day_key = created_at.date().isoformat()
        if day_key in daily[category]:
            daily[category][day_key] += 1
        for suffix, (_, bucket_minutes) in rolling_specs.items():
            if created_at < rolling_starts[suffix]:
                continue
            bucket = created_at.replace(
                minute=(created_at.minute // bucket_minutes) * bucket_minutes,
                second=0,
                microsecond=0,
            ).isoformat()
            if bucket in rolling[category][suffix]:
                rolling[category][suffix][bucket] += 1

    result: dict[str, list[dict[str, Any]]] = {}
    for category in categories:
        result[category] = [{"date": key, "value": value} for key, value in daily[category].items()]
        for suffix in rolling_specs:
            result[f"{category}_{suffix}"] = [
                {"date": key, "value": value}
                for key, value in rolling[category][suffix].items()
            ]
    return result


def _time_buckets(
    current: datetime,
    *,
    days: int,
) -> tuple[list[str], dict[str, tuple[int, int]], dict[str, list[datetime]]]:
    local_current = current.astimezone(MOSCOW)
    daily_keys = [
        (local_current.date() - timedelta(days=offset)).isoformat()
        for offset in range(days - 1, -1, -1)
    ]
    rolling_specs = {
        "1h": (60, 5),
        "6h": (360, 30),
        "12h": (720, 60),
        "24h": (1440, 60),
    }
    buckets: dict[str, list[datetime]] = {}
    for suffix, (minutes, bucket_minutes) in rolling_specs.items():
        end = current.replace(
            minute=(current.minute // bucket_minutes) * bucket_minutes,
            second=0,
            microsecond=0,
        )
        count = max(1, (minutes + bucket_minutes - 1) // bucket_minutes)
        buckets[suffix] = [
            end - timedelta(minutes=bucket_minutes * offset)
            for offset in range(count - 1, -1, -1)
        ]
    return daily_keys, rolling_specs, buckets


def dashboard_presence_timeline(
    conn: sqlite3.Connection,
    *,
    days: int = 90,
    now: datetime | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Distinct users with a heartbeat inside each visible time bucket."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    daily_keys, rolling_specs, buckets = _time_buckets(current, days=days)
    daily: dict[str, set[str]] = {key: set() for key in daily_keys}
    rolling: dict[str, dict[str, set[str]]] = {
        suffix: {bucket.isoformat(): set() for bucket in values}
        for suffix, values in buckets.items()
    }
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_presence_samples'"
    ).fetchone()
    if table_exists:
        start = min(values[0] for values in buckets.values())
        daily_start = datetime.combine(
            datetime.fromisoformat(daily_keys[0]).date(), datetime.min.time(), MOSCOW
        ).astimezone(timezone.utc)
        rows = conn.execute(
            "SELECT bucket_at,COALESCE(internal_user_id,user_id) identity "
            "FROM user_presence_samples WHERE bucket_at>=? ORDER BY bucket_at",
            (min(start, daily_start).isoformat(),),
        ).fetchall()
        for row in rows:
            created_at = _parse_utc(row["bucket_at"])
            identity = str(row["identity"] or "")
            if created_at is None or created_at > current or not identity:
                continue
            day_key = created_at.astimezone(MOSCOW).date().isoformat()
            if day_key in daily:
                daily[day_key].add(identity)
            for suffix, (_, bucket_minutes) in rolling_specs.items():
                if created_at < buckets[suffix][0]:
                    continue
                bucket_key = created_at.replace(
                    minute=(created_at.minute // bucket_minutes) * bucket_minutes,
                    second=0,
                    microsecond=0,
                ).isoformat()
                if bucket_key in rolling[suffix]:
                    rolling[suffix][bucket_key].add(identity)
    result = {
        "active_users": [{"date": key, "value": len(value)} for key, value in daily.items()]
    }
    for suffix in rolling_specs:
        result[f"active_users_{suffix}"] = [
            {"date": key, "value": len(value)} for key, value in rolling[suffix].items()
        ]
    return result


def dashboard_payment_timeline(
    conn: sqlite3.Connection,
    *,
    days: int = 90,
    now: datetime | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Successful and failed payment counts for the dashboard chart."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    daily_keys, rolling_specs, buckets = _time_buckets(current, days=days)
    categories = ("payments_paid", "payments_failed")
    daily = {category: {key: 0 for key in daily_keys} for category in categories}
    rolling = {
        category: {
            suffix: {bucket.isoformat(): 0 for bucket in values}
            for suffix, values in buckets.items()
        }
        for category in categories
    }
    daily_start = datetime.combine(
        datetime.fromisoformat(daily_keys[0]).date(), datetime.min.time(), MOSCOW
    ).astimezone(timezone.utc)
    rows = conn.execute(
        "SELECT status,COALESCE(paid_at,created_at) event_at FROM payments "
        "WHERE COALESCE(paid_at,created_at)>=? ORDER BY event_at",
        (daily_start.isoformat(),),
    ).fetchall()
    paid_statuses = {"paid", "partially_refunded", "refunded"}
    failed_statuses = {"failed", "canceled", "cancelled"}
    for row in rows:
        status = str(row["status"] or "").lower()
        category = "payments_paid" if status in paid_statuses else "payments_failed" if status in failed_statuses else None
        created_at = _parse_utc(row["event_at"])
        if category is None or created_at is None or created_at > current:
            continue
        day_key = created_at.astimezone(MOSCOW).date().isoformat()
        if day_key in daily[category]:
            daily[category][day_key] += 1
        for suffix, (_, bucket_minutes) in rolling_specs.items():
            if created_at < buckets[suffix][0]:
                continue
            bucket_key = created_at.replace(
                minute=(created_at.minute // bucket_minutes) * bucket_minutes,
                second=0,
                microsecond=0,
            ).isoformat()
            if bucket_key in rolling[category][suffix]:
                rolling[category][suffix][bucket_key] += 1
    result: dict[str, list[dict[str, Any]]] = {}
    for category in categories:
        result[category] = [{"date": key, "value": value} for key, value in daily[category].items()]
        for suffix in rolling_specs:
            result[f"{category}_{suffix}"] = [
                {"date": key, "value": value} for key, value in rolling[category][suffix].items()
            ]
    return result


def dashboard_payment_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        "SELECT COUNT(*) total_attempts,"
        "SUM(CASE WHEN status IN ('paid','partially_refunded','refunded') THEN 1 ELSE 0 END) paid_count,"
        "SUM(CASE WHEN status IN ('failed','canceled','cancelled') THEN 1 ELSE 0 END) failed_count,"
        "SUM(CASE WHEN status IN ('paid','partially_refunded','refunded') THEN amount ELSE 0 END) revenue_rub "
        "FROM payments"
    ).fetchone()
    return {
        "total_attempts": int(row["total_attempts"] or 0),
        "paid_count": int(row["paid_count"] or 0),
        "failed_count": int(row["failed_count"] or 0),
        "revenue_rub": int(row["revenue_rub"] or 0),
    }

