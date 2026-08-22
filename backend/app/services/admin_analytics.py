"""Read-only CRM analytics projections.

The customer product has two visible token accounts: the daily tariff allowance
and the main balance.  Admin projections keep those accounts separate and use a
single business-day boundary (Europe/Moscow, UTC+03:00) for all "today" values.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import HTTPException, Request


MOSCOW = timezone(timedelta(hours=3), name="Europe/Moscow")
IMAGE_JOB_MODES = {
    "text_to_image", "image_to_image", "edit", "paint", "inpaint",
    "outpaint", "faceswap", "remove_background",
}
VIDEO_JOB_MODES = {
    "text_to_video", "image_to_video", "first_last_frame", "reference_to_video",
}


def business_periods(now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    local_now = current.astimezone(MOSCOW)
    today_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    today = today_local.astimezone(timezone.utc)
    yesterday = today - timedelta(days=1)
    return {
        "generated_at": current.isoformat(),
        "timezone": "Europe/Moscow",
        "today_start": today.isoformat(),
        "yesterday_start": yesterday.isoformat(),
        "last_24h_start": (current - timedelta(hours=24)).isoformat(),
    }


def _scalar(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(query, params).fetchone()
    return int(row[0] or 0)


def _job_kind_sql(kind: str) -> tuple[str, tuple[str, ...]]:
    modes = tuple(sorted(VIDEO_JOB_MODES if kind == "video" else IMAGE_JOB_MODES))
    return f"mode IN ({','.join('?' for _ in modes)})", modes


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


def job_metrics(
    conn: sqlite3.Connection,
    start: str,
    end: str | None = None,
    *,
    user_id: str | None = None,
) -> dict[str, int]:
    clauses = ["created_at >= ?"]
    params: list[Any] = [start]
    if end:
        clauses.append("created_at < ?")
        params.append(end)
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    where = " AND ".join(clauses)
    image_sql, image_modes = _job_kind_sql("image")
    video_sql, video_modes = _job_kind_sql("video")
    return {
        "total": _scalar(conn, f"SELECT COUNT(*) FROM jobs WHERE {where}", tuple(params)),
        "completed": _scalar(conn, f"SELECT COUNT(*) FROM jobs WHERE {where} AND status='completed'", tuple(params)),
        "failed": _scalar(conn, f"SELECT COUNT(*) FROM jobs WHERE {where} AND status='failed'", tuple(params)),
        "running": _scalar(conn, f"SELECT COUNT(*) FROM jobs WHERE {where} AND status NOT IN ('completed','failed')", tuple(params)),
        "images": _scalar(conn, f"SELECT COUNT(*) FROM jobs WHERE {where} AND {image_sql}", (*params, *image_modes)),
        "videos": _scalar(conn, f"SELECT COUNT(*) FROM jobs WHERE {where} AND {video_sql}", (*params, *video_modes)),
    }


def token_metrics(
    conn: sqlite3.Connection,
    start: str,
    end: str | None = None,
    *,
    user_id: str | None = None,
) -> dict[str, int]:
    clauses = ["created_at >= ?"]
    params: list[Any] = [start]
    if end:
        clauses.append("created_at < ?")
        params.append(end)
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    rows = conn.execute(
        f"SELECT delta, reason, meta_json FROM token_ledger WHERE {' AND '.join(clauses)}",
        tuple(params),
    ).fetchall()
    daily = main = total = refunds = 0
    for row in rows:
        try:
            metadata = json.loads(row["meta_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        reason = str(row["reason"] or "")
        delta = int(row["delta"] or 0)
        if "refund" in reason:
            refunds += abs(delta) + int(metadata.get("daily_part") or 0)
            continue
        daily_part = int(metadata.get("daily_part") or 0)
        main_part = int(metadata.get("balance_part") or max(0, -delta))
        token_cost = int(metadata.get("token_cost") or (daily_part + main_part))
        if token_cost <= 0 and delta < 0:
            token_cost = -delta
        daily += max(0, daily_part)
        main += max(0, main_part)
        total += max(0, token_cost)
    return {"total": total, "daily": daily, "main": main, "refunds": refunds}


def dashboard_projection(conn: sqlite3.Connection, now: datetime | None = None) -> dict[str, Any]:
    periods = business_periods(now)
    today = periods["today_start"]
    yesterday = periods["yesterday_start"]
    last_24h = periods["last_24h_start"]
    now_iso = periods["generated_at"]
    login_names = "('login_succeeded','password_login_succeeded','password_register_succeeded')"

    def user_metrics(start: str, end: str | None = None) -> dict[str, int]:
        end_clause = " AND created_at < ?" if end else ""
        args = (start, end) if end else (start,)
        seen_end_clause = " AND last_seen_at < ?" if end else ""
        return {
            "active": _scalar(conn, f"SELECT COUNT(*) FROM users WHERE internal_user_id IS NOT NULL AND last_seen_at >= ?{seen_end_clause}", args),
            "new": _scalar(conn, f"SELECT COUNT(*) FROM users WHERE internal_user_id IS NOT NULL AND created_at >= ?{end_clause}", args),
            "logins": _scalar(conn, f"SELECT COUNT(*) FROM event_logs WHERE event_name IN {login_names} AND created_at >= ?{end_clause}", args),
        }

    def period(start: str, end: str | None = None) -> dict[str, Any]:
        return {
            "users": user_metrics(start, end),
            "generations": job_metrics(conn, start, end),
            "tokens": token_metrics(conn, start, end),
        }

    providers = {
        str(row["provider"]): int(row["count"])
        for row in conn.execute(
            "SELECT provider, COUNT(DISTINCT internal_user_id) count FROM auth_identities GROUP BY provider"
        )
    }
    return {
        "generated_at": periods["generated_at"],
        "timezone": periods["timezone"],
        "periods": {
            "today": period(today),
            "yesterday": period(yesterday, today),
            "last_24h": period(last_24h),
        },
        "totals": {
            "users": _scalar(conn, "SELECT COUNT(*) FROM users WHERE internal_user_id IS NOT NULL"),
            "generations": _scalar(conn, "SELECT COUNT(*) FROM jobs"),
            "images": _scalar(conn, "SELECT COUNT(*) FROM images WHERE deleted_at IS NULL OR deleted_at=''"),
            "videos": _scalar(conn, "SELECT COUNT(*) FROM videos WHERE deleted_at IS NULL OR deleted_at=''"),
            "failed_generations": _scalar(conn, "SELECT COUNT(*) FROM jobs WHERE status='failed'"),
            "main_token_balance": _scalar(conn, "SELECT COALESCE(SUM(token_balance),0) FROM users"),
            "main_tokens_spent": _scalar(conn, "SELECT COALESCE(SUM(-delta),0) FROM token_ledger WHERE delta<0"),
        },
        "sessions_active": _scalar(
            conn,
            "SELECT COUNT(*) FROM auth_sessions WHERE revoked_at IS NULL AND expires_at > ?",
            (now_iso,),
        ),
        "users_by_provider": providers,
    }


def user_period_projection(
    conn: sqlite3.Connection,
    user_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    periods = business_periods(now)
    today = periods["today_start"]
    yesterday = periods["yesterday_start"]
    last_generation = conn.execute(
        "SELECT created_at FROM jobs WHERE user_id=? ORDER BY created_at DESC LIMIT 1", (user_id,)
    ).fetchone()
    total_jobs = {
        "total": _scalar(conn, "SELECT COUNT(*) FROM jobs WHERE user_id=?", (user_id,)),
        "completed": _scalar(conn, "SELECT COUNT(*) FROM jobs WHERE user_id=? AND status='completed'", (user_id,)),
        "failed": _scalar(conn, "SELECT COUNT(*) FROM jobs WHERE user_id=? AND status='failed'", (user_id,)),
    }
    image_sql, image_modes = _job_kind_sql("image")
    video_sql, video_modes = _job_kind_sql("video")
    total_jobs["images"] = _scalar(conn, f"SELECT COUNT(*) FROM jobs WHERE user_id=? AND {image_sql}", (user_id, *image_modes))
    total_jobs["videos"] = _scalar(conn, f"SELECT COUNT(*) FROM jobs WHERE user_id=? AND {video_sql}", (user_id, *video_modes))
    return {
        "last_generation_at": last_generation["created_at"] if last_generation else None,
        "generations": {
            "today": job_metrics(conn, today, user_id=user_id),
            "yesterday": job_metrics(conn, yesterday, today, user_id=user_id),
            "total": total_jobs,
        },
        "token_usage": {
            "today": token_metrics(conn, today, user_id=user_id),
            "yesterday": token_metrics(conn, yesterday, today, user_id=user_id),
        },
    }


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _device(metadata_json: str | None) -> dict[str, str | None]:
    metadata = _json_object(metadata_json)
    nested = metadata.get("device")
    if isinstance(nested, dict):
        metadata = {**metadata, **nested}
    return {
        "browser": metadata.get("browser") or metadata.get("browser_name"),
        "os": metadata.get("os") or metadata.get("os_name"),
        "device_type": metadata.get("device_type") or metadata.get("deviceType"),
        "app_build": metadata.get("app_build") or metadata.get("appBuild"),
    }


def _short(value: Any, length: int = 8) -> str | None:
    text = str(value or "")
    return f"{text[:length]}…" if len(text) > length else (text or None)


def _text(value: Any, length: int) -> str | None:
    text = str(value or "").strip()
    return text[:length] if text else None


def _event_details(value: Any) -> dict[str, Any]:
    blocked = ("token", "hash", "password", "secret", "cookie", "authorization", "raw_profile")
    result: dict[str, Any] = {}
    for key, raw in _json_object(value).items():
        if any(part in str(key).lower() for part in blocked):
            continue
        if isinstance(raw, (str, int, float, bool)) or raw is None:
            result[str(key)] = _text(raw, 240) if isinstance(raw, str) else raw
    return result


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _elapsed_seconds(started_at: Any, completed_at: Any) -> float | None:
    if not started_at or not completed_at:
        return None
    try:
        started = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        completed = datetime.fromisoformat(str(completed_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return round(max(0.0, (completed - started).total_seconds()), 3)


def _local_day(value: Any) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(MOSCOW).date().isoformat()


def _user_activity_series(
    conn: sqlite3.Connection,
    internal_user_id: str,
    user_id: str,
    *,
    now: datetime | None = None,
    days: int = 14,
) -> dict[str, Any]:
    """Return a compact Moscow-time activity/economics series for the CRM chart."""
    current = (now or datetime.now(timezone.utc)).astimezone(MOSCOW)
    day_count = max(7, min(31, int(days)))
    first_day = current.date() - timedelta(days=day_count - 1)
    keys = [(first_day + timedelta(days=index)).isoformat() for index in range(day_count)]
    points: dict[str, dict[str, Any]] = {
        key: {
            "date": key,
            "logins": 0,
            "active_minutes": 0,
            "local_images": 0,
            "api_images": 0,
            "videos": 0,
            "main_tokens": 0,
            "daily_tokens": 0,
            "refunded_tokens": 0,
            "api_cost_rub": 0.0,
            "unreconciled_api_cost_rub": 0.0,
            "unreconciled_api_jobs": 0,
            "revenue_rub": 0,
            "refund_rub": 0,
            "net_revenue_rub": 0,
        }
        for key in keys
    }

    start_local = datetime.combine(first_day, datetime.min.time(), tzinfo=MOSCOW)
    start_iso = start_local.astimezone(timezone.utc).isoformat()
    for row in conn.execute(
        "SELECT created_at FROM auth_login_attempts WHERE internal_user_id=? AND success=1 AND created_at>=?",
        (internal_user_id, start_iso),
    ):
        key = _local_day(row["created_at"])
        if key in points:
            points[key]["logins"] += 1

    presence_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_presence_samples'"
    ).fetchone()
    if presence_table:
        for row in conn.execute(
            "SELECT bucket_at,active_seconds FROM user_presence_samples "
            "WHERE (internal_user_id=? OR (internal_user_id IS NULL AND user_id=?)) AND bucket_at>=?",
            (internal_user_id, user_id, start_iso),
        ):
            key = _local_day(row["bucket_at"])
            if key in points:
                points[key]["active_minutes"] += min(300, max(0, int(row["active_seconds"] or 0))) / 60

    calibration = _video_cost_calibration(conn)
    for row in conn.execute(
        "SELECT mode,provider,status,settings_json,created_at,started_at,completed_at FROM jobs WHERE user_id=? AND created_at>=?",
        (user_id, start_iso),
    ):
        key = _local_day(row["created_at"])
        if key not in points:
            continue
        mode = str(row["mode"] or "")
        if mode in VIDEO_JOB_MODES:
            points[key]["videos"] += 1
        elif str(row["provider"] or "") == "comfyui":
            points[key]["local_images"] += 1
        else:
            points[key]["api_images"] += 1
        settings = _json_object(row["settings_json"])
        economics = _generation_economics(
            settings,
            row["status"],
            provider=row["provider"],
            mode=row["mode"],
            elapsed_seconds=_elapsed_seconds(row["started_at"] or row["created_at"], row["completed_at"]),
            cost_multiplier=calibration.get(_video_cost_key(settings, row["mode"]), 1.0),
        )
        if economics["cost_kind"] == "actual":
            points[key]["api_cost_rub"] += float(economics["actual_cost_rub"] or 0)
        elif economics["cost_kind"] == "unreconciled_estimate":
            points[key]["unreconciled_api_cost_rub"] += float(economics["unreconciled_cost_rub"] or 0)
            points[key]["unreconciled_api_jobs"] += 1

    for row in conn.execute(
        "SELECT delta,reason,meta_json,created_at FROM token_ledger WHERE user_id=? AND created_at>=?",
        (user_id, start_iso),
    ):
        key = _local_day(row["created_at"])
        if key not in points:
            continue
        metadata = _json_object(row["meta_json"])
        delta = int(row["delta"] or 0)
        reason = str(row["reason"] or "")
        if "refund" in reason:
            points[key]["refunded_tokens"] += int(
                metadata.get("token_cost")
                or int(metadata.get("daily_part") or 0) + int(metadata.get("balance_part") or max(0, delta))
            )
        else:
            points[key]["daily_tokens"] += max(0, int(metadata.get("daily_part") or 0))
            points[key]["main_tokens"] += max(0, int(metadata.get("balance_part") or max(0, -delta)))

    for row in conn.execute(
        "SELECT amount,paid_at,created_at FROM payments WHERE internal_user_id=? "
        "AND status IN ('paid','partially_refunded','refunded') AND COALESCE(paid_at,created_at)>=?",
        (internal_user_id, start_iso),
    ):
        key = _local_day(row["paid_at"] or row["created_at"])
        if key in points:
            points[key]["revenue_rub"] += int(row["amount"] or 0)
    for row in conn.execute(
        "SELECT amount,completed_at,created_at FROM refunds WHERE internal_user_id=? "
        "AND status IN ('completed','succeeded') AND COALESCE(completed_at,created_at)>=?",
        (internal_user_id, start_iso),
    ):
        key = _local_day(row["completed_at"] or row["created_at"])
        if key in points:
            points[key]["refund_rub"] += int(row["amount"] or 0)

    for point in points.values():
        point["active_minutes"] = round(float(point["active_minutes"]), 1)
        point["api_cost_rub"] = round(float(point["api_cost_rub"]), 2)
        point["unreconciled_api_cost_rub"] = round(float(point["unreconciled_api_cost_rub"]), 2)
        point["net_revenue_rub"] = int(point["revenue_rub"]) - int(point["refund_rub"])
    values = list(points.values())
    return {
        "timezone": "Europe/Moscow",
        "days": values,
        "totals": {
            name: round(sum(float(point[name]) for point in values), 2)
            if name in {"active_minutes", "api_cost_rub", "unreconciled_api_cost_rub"} else sum(int(point[name]) for point in values)
            for name in (
                "logins", "active_minutes", "local_images", "api_images", "videos", "main_tokens",
                "daily_tokens", "refunded_tokens", "api_cost_rub", "revenue_rub",
                "refund_rub", "net_revenue_rub", "unreconciled_api_cost_rub", "unreconciled_api_jobs",
            )
        },
    }


def _video_cost_key(settings: dict[str, Any], mode: Any) -> tuple[str, str, str, bool]:
    return (
        str(settings.get("openrouterModel") or settings.get("model") or ""),
        str(mode or ""),
        str(settings.get("resolution") or "").lower(),
        bool(settings.get("generateAudio")),
    )


def _video_cost_calibration(conn: sqlite3.Connection) -> dict[tuple[str, str, str, bool], float]:
    totals: dict[tuple[str, str, str, bool], list[float]] = {}
    for row in conn.execute(
        "SELECT mode,settings_json FROM jobs WHERE provider='openrouter' AND status='completed' "
        "AND mode IN ('text_to_video','image_to_video','first_last_frame','reference_to_video')"
    ):
        settings = _json_object(row["settings_json"])
        billing = settings.get("openrouterBilling") if isinstance(settings.get("openrouterBilling"), dict) else {}
        actual = _number(billing.get("actualCostUsd"))
        if actual is None:
            actual = _number(settings.get("openrouterCostUsd"))
        estimated = _number(billing.get("estimatedCostUsd"))
        if actual is None or estimated is None or actual <= 0 or estimated <= 0:
            continue
        bucket = totals.setdefault(_video_cost_key(settings, row["mode"]), [0.0, 0.0])
        bucket[0] += actual
        bucket[1] += estimated
    return {
        key: max(1.0, values[0] / values[1])
        for key, values in totals.items()
        if values[1] > 0
    }


def _generation_economics(
    settings: dict[str, Any],
    status: Any,
    *,
    provider: Any = None,
    mode: Any = None,
    elapsed_seconds: float | None = None,
    cost_multiplier: float = 1.0,
) -> dict[str, Any]:
    billing = settings.get("openrouterBilling") if isinstance(settings.get("openrouterBilling"), dict) else {}
    actual_usd = _number(billing.get("actualCostUsd"))
    if actual_usd is None:
        actual_usd = _number(settings.get("openrouterCostUsd"))
    actual_rub = _number(billing.get("actualCostRub"))
    estimated_usd = _number(billing.get("estimatedCostUsd"))
    estimated_rub = _number(billing.get("estimatedCostRub"))
    effective_rate = _number(billing.get("effectiveUsdRub"))
    if actual_rub is None and actual_usd is not None and effective_rate is not None:
        actual_rub = actual_usd * effective_rate
    if estimated_rub is None and estimated_usd is not None and effective_rate is not None:
        estimated_rub = estimated_usd * effective_rate
    completed = str(status or "") == "completed"
    has_actual = completed and actual_usd is not None
    explicit_unknown = bool(billing.get("providerCostUncertain")) or str(settings.get("openrouterSubmissionState") or "") == "provider_response_timeout"
    historical_timeout = (
        str(status or "") == "failed"
        and str(provider or "") == "openrouter"
        and str(mode or "") in VIDEO_JOB_MODES
        and "openrouterSubmitError" in settings
        and not settings.get("openrouterJobId")
        and elapsed_seconds is not None
        and 25 <= float(elapsed_seconds) <= 45
    )
    unreconciled = not has_actual and estimated_usd is not None and (explicit_unknown or historical_timeout)
    multiplier = max(1.0, float(cost_multiplier or 1.0)) if unreconciled else 1.0
    unreconciled_usd = estimated_usd * multiplier if unreconciled and estimated_usd is not None else None
    unreconciled_rub = estimated_rub * multiplier if unreconciled and estimated_rub is not None else None
    return {
        "actual_cost_usd": round(actual_usd, 6) if has_actual else None,
        "actual_cost_rub": round(actual_rub, 2) if has_actual and actual_rub is not None else None,
        "estimated_cost_usd": round(estimated_usd, 6) if estimated_usd is not None else None,
        "estimated_cost_rub": round(estimated_rub, 2) if estimated_rub is not None else None,
        "unreconciled_cost_usd": round(unreconciled_usd, 6) if unreconciled_usd is not None else None,
        "unreconciled_cost_rub": round(unreconciled_rub, 2) if unreconciled_rub is not None else None,
        "cost_calibration_multiplier": round(multiplier, 4) if unreconciled else None,
        "cost_kind": "actual" if has_actual else "unreconciled_estimate" if unreconciled else ("estimated" if estimated_usd is not None else "unpriced"),
    }


def _token_job_map(conn: sqlite3.Connection, user_id: str) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for row in conn.execute("SELECT delta,reason,meta_json FROM token_ledger WHERE user_id=?", (user_id,)):
        metadata = _json_object(row["meta_json"])
        job_id = str(metadata.get("jobId") or metadata.get("job_id") or "")
        if not job_id:
            continue
        item = result.setdefault(job_id, {"main": 0, "daily": 0, "refunded": 0})
        reason = str(row["reason"] or "")
        if "refund" in reason:
            item["refunded"] += int(metadata.get("token_cost") or abs(int(row["delta"] or 0)))
        else:
            item["daily"] += max(0, int(metadata.get("daily_part") or 0))
            item["main"] += max(0, int(metadata.get("balance_part") or max(0, -int(row["delta"] or 0))))
    return result


def _finance_projection(conn: sqlite3.Connection, internal_user_id: str, user_id: str) -> dict[str, Any]:
    grants = main_refunded = daily_refunded = main_debited = daily_debited = ledger_entries = refund_entries = 0
    for row in conn.execute("SELECT delta,reason,meta_json FROM token_ledger WHERE user_id=?", (user_id,)):
        ledger_entries += 1
        delta = int(row["delta"] or 0)
        reason = str(row["reason"] or "")
        metadata = _json_object(row["meta_json"])
        if "refund" in reason:
            refund_entries += 1
            daily_refunded += max(0, int(metadata.get("daily_part") or 0))
            main_refunded += max(0, int(metadata.get("balance_part") or max(0, delta)))
        elif delta > 0:
            grants += delta
        else:
            main_debited += max(0, int(metadata.get("balance_part") or -delta))
            daily_debited += max(0, int(metadata.get("daily_part") or 0))

    actual_usd = actual_rub = 0.0
    unreconciled_usd = unreconciled_rub = 0.0
    actual_jobs = unreconciled_jobs = local_jobs = 0
    local_seconds = 0.0
    calibration = _video_cost_calibration(conn)
    for row in conn.execute("SELECT mode,provider,status,settings_json,created_at,started_at,completed_at FROM jobs WHERE user_id=?", (user_id,)):
        settings = _json_object(row["settings_json"])
        economics = _generation_economics(
            settings,
            row["status"],
            provider=row["provider"],
            mode=row["mode"],
            elapsed_seconds=_elapsed_seconds(row["started_at"] or row["created_at"], row["completed_at"]),
            cost_multiplier=calibration.get(_video_cost_key(settings, row["mode"]), 1.0),
        )
        if economics["cost_kind"] == "actual":
            actual_jobs += 1
            actual_usd += float(economics["actual_cost_usd"] or 0)
            actual_rub += float(economics["actual_cost_rub"] or 0)
        elif economics["cost_kind"] == "unreconciled_estimate":
            unreconciled_jobs += 1
            unreconciled_usd += float(economics["unreconciled_cost_usd"] or 0)
            unreconciled_rub += float(economics["unreconciled_cost_rub"] or 0)
        if str(row["provider"] or "") == "comfyui" and str(row["status"] or "") == "completed":
            duration = _elapsed_seconds(row["started_at"] or row["created_at"], row["completed_at"])
            if duration is not None:
                local_jobs += 1
                local_seconds += duration

    paid = conn.execute(
        "SELECT COALESCE(SUM(amount),0) amount FROM payments WHERE internal_user_id=? AND status IN ('paid','partially_refunded','refunded')",
        (internal_user_id,),
    ).fetchone()
    returned = conn.execute(
        "SELECT COALESCE(SUM(amount),0) amount FROM refunds WHERE internal_user_id=? AND status IN ('completed','succeeded')",
        (internal_user_id,),
    ).fetchone()
    return {
        "token_economics": {
            "current_balance": _scalar(conn, "SELECT token_balance FROM users WHERE id=?", (user_id,)),
            "granted": grants,
            "main_debited": main_debited,
            "refunded": main_refunded + daily_refunded,
            "main_refunded": main_refunded,
            "daily_refunded": daily_refunded,
            "main_consumed": max(0, main_debited - main_refunded),
            "daily_consumed": max(0, daily_debited - daily_refunded),
            "total_consumed": max(0, main_debited - main_refunded) + max(0, daily_debited - daily_refunded),
            "ledger_entries": ledger_entries,
            "refund_entries": refund_entries,
        },
        "generation_economics": {
            "actual_api_cost_usd": round(actual_usd, 6),
            "actual_api_cost_rub": round(actual_rub, 2),
            "actual_api_jobs": actual_jobs,
            "unreconciled_api_cost_usd": round(unreconciled_usd, 6),
            "unreconciled_api_cost_rub": round(unreconciled_rub, 2),
            "unreconciled_api_jobs": unreconciled_jobs,
            "potential_api_cost_usd": round(actual_usd + unreconciled_usd, 6),
            "potential_api_cost_rub": round(actual_rub + unreconciled_rub, 2),
            "local_completed_jobs": local_jobs,
            "local_compute_seconds": round(local_seconds, 3),
            "local_cost_configured": False,
            "local_cost_rub": None,
        },
        "cash_economics": {
            "paid_rub": int(paid["amount"] or 0),
            "refunded_rub": int(returned["amount"] or 0),
            "net_received_rub": int(paid["amount"] or 0) - int(returned["amount"] or 0),
            "margin_before_local_cost_rub": round(
                int(paid["amount"] or 0) - int(returned["amount"] or 0) - actual_rub,
                2,
            ),
            "potential_margin_after_unreconciled_rub": round(
                int(paid["amount"] or 0) - int(returned["amount"] or 0) - actual_rub - unreconciled_rub,
                2,
            ),
        },
    }


def user_dossier_enrichment(
    conn: sqlite3.Connection,
    internal_user_id: str,
    user_id: str,
    now_iso: str,
) -> dict[str, Any]:
    access = conn.execute(
        "SELECT COUNT(*) attempts, SUM(success=1) successful, SUM(success=0) failed, "
        "MIN(CASE WHEN success=1 THEN created_at END) first_success_at, "
        "MAX(CASE WHEN success=1 THEN created_at END) last_success_at "
        "FROM auth_login_attempts WHERE internal_user_id=?", (internal_user_id,),
    ).fetchone()
    counts = conn.execute(
        "SELECT (SELECT COUNT(*) FROM auth_sessions WHERE internal_user_id=?) sessions, "
        "(SELECT COUNT(*) FROM auth_sessions WHERE internal_user_id=? AND revoked_at IS NULL AND expires_at>?) active_sessions, "
        "(SELECT COUNT(*) FROM device_installations WHERE internal_user_id=?) devices, "
        "(SELECT COUNT(*) FROM session_events WHERE internal_user_id=?) session_events",
        (internal_user_id, internal_user_id, now_iso, internal_user_id, internal_user_id),
    ).fetchone()
    ips = conn.execute(
        "WITH seen(ip, seen_at, source, success) AS ("
        " SELECT ip_address, created_at, 'session', 1 FROM auth_sessions WHERE internal_user_id=?"
        " UNION ALL SELECT ip_address, created_at, 'login', success FROM auth_login_attempts WHERE internal_user_id=?"
        " UNION ALL SELECT ip_address, created_at, 'event', 1 FROM event_logs WHERE internal_user_id=?"
        " UNION ALL SELECT ip_address, created_at, 'security', 0 FROM security_events WHERE internal_user_id=?"
        ") SELECT ip, MIN(seen_at) first_seen_at, MAX(seen_at) last_seen_at, COUNT(*) seen_count, "
        "SUM(source='login' AND success=1) successful_logins, SUM(source='login' AND success=0) failed_logins, "
        "GROUP_CONCAT(DISTINCT source) sources FROM seen WHERE ip IS NOT NULL AND ip!='' GROUP BY ip ORDER BY last_seen_at DESC",
        (internal_user_id,) * 4,
    ).fetchall()
    client_rows = conn.execute(
        "SELECT 'session' source, platform, created_at first_seen_at, last_seen_at, metadata_json FROM auth_sessions WHERE internal_user_id=? "
        "UNION ALL SELECT 'device', platform, first_seen_at, last_seen_at, metadata_json FROM device_installations WHERE internal_user_id=?",
        (internal_user_id, internal_user_id),
    ).fetchall()
    clients: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in client_rows:
        parsed = _device(row["metadata_json"])
        key = tuple(str(v or fallback) for v, fallback in zip(
            (parsed["browser"], parsed["os"], parsed["device_type"], row["platform"]),
            ("Не определён", "Не определена", "Не определено", "—"), strict=True,
        ))
        item = clients.setdefault(key, {"browser": key[0], "os": key[1], "device_type": key[2], "platform": key[3], "seen_count": 0, "first_seen_at": row["first_seen_at"], "last_seen_at": row["last_seen_at"], "sources": set()})
        item["seen_count"] += 1
        item["first_seen_at"] = min(filter(None, (item["first_seen_at"], row["first_seen_at"])), default=None)
        item["last_seen_at"] = max(filter(None, (item["last_seen_at"], row["last_seen_at"])), default=None)
        item["sources"].add(row["source"])
    client_history = sorted(clients.values(), key=lambda item: item.get("last_seen_at") or "", reverse=True)
    for item in client_history:
        item["sources"] = sorted(item["sources"])
    job_tokens = _token_job_map(conn, user_id)
    calibration = _video_cost_calibration(conn)
    models: dict[tuple[str, str], dict[str, Any]] = {}
    for row in conn.execute("SELECT id,mode,provider,status,settings_json,created_at,started_at,completed_at FROM jobs WHERE user_id=?", (user_id,)):
        settings = _json_object(row["settings_json"])
        provider = str(row["provider"] or "—")
        model = str(settings.get("modelProfile") or settings.get("openrouterModel") or settings.get("model") or provider)
        item = models.setdefault((provider, model), {"provider": provider, "model": model, "total": 0, "completed": 0, "failed": 0, "last_used_at": None, "main_tokens": 0, "daily_tokens": 0, "refunded_tokens": 0, "actual_cost_usd": 0.0, "actual_cost_rub": 0.0, "actual_cost_jobs": 0, "unreconciled_cost_usd": 0.0, "unreconciled_cost_rub": 0.0, "unreconciled_cost_jobs": 0, "elapsed_seconds": 0.0})
        item["total"] += 1
        if row["status"] == "completed": item["completed"] += 1
        if row["status"] == "failed": item["failed"] += 1
        item["last_used_at"] = max(filter(None, (item["last_used_at"], row["created_at"])), default=None)
        tokens = job_tokens.get(str(row["id"]), {})
        item["main_tokens"] += int(tokens.get("main", 0))
        item["daily_tokens"] += int(tokens.get("daily", 0))
        item["refunded_tokens"] += int(tokens.get("refunded", 0))
        economics = _generation_economics(
            settings,
            row["status"],
            provider=row["provider"],
            mode=row["mode"],
            elapsed_seconds=_elapsed_seconds(row["started_at"] or row["created_at"], row["completed_at"]),
            cost_multiplier=calibration.get(_video_cost_key(settings, row["mode"]), 1.0),
        )
        if economics["cost_kind"] == "actual":
            item["actual_cost_jobs"] += 1
            item["actual_cost_usd"] += float(economics["actual_cost_usd"] or 0)
            item["actual_cost_rub"] += float(economics["actual_cost_rub"] or 0)
        elif economics["cost_kind"] == "unreconciled_estimate":
            item["unreconciled_cost_jobs"] += 1
            item["unreconciled_cost_usd"] += float(economics["unreconciled_cost_usd"] or 0)
            item["unreconciled_cost_rub"] += float(economics["unreconciled_cost_rub"] or 0)
        elapsed = _elapsed_seconds(row["started_at"] or row["created_at"], row["completed_at"])
        if elapsed is not None:
            item["elapsed_seconds"] += elapsed
    for item in models.values():
        item["actual_cost_usd"] = round(float(item["actual_cost_usd"]), 6)
        item["actual_cost_rub"] = round(float(item["actual_cost_rub"]), 2)
        item["unreconciled_cost_usd"] = round(float(item["unreconciled_cost_usd"]), 6)
        item["unreconciled_cost_rub"] = round(float(item["unreconciled_cost_rub"]), 2)
        item["elapsed_seconds"] = round(float(item["elapsed_seconds"]), 3)
        item["net_tokens"] = max(0, int(item["main_tokens"]) + int(item["daily_tokens"]) - int(item["refunded_tokens"]))
        item["provider_kind"] = "local" if item["provider"] == "comfyui" else "api"
    total_queries = {
        "events": ("SELECT COUNT(*) FROM event_logs WHERE internal_user_id=?", internal_user_id),
        "security_events": ("SELECT COUNT(*) FROM security_events WHERE internal_user_id=?", internal_user_id),
        "admin_actions": ("SELECT COUNT(*) FROM audit_logs WHERE target_internal_user_id=?", internal_user_id),
        "generations": ("SELECT COUNT(*) FROM jobs WHERE user_id=?", user_id),
        "images": ("SELECT COUNT(*) FROM images WHERE user_id=? AND (deleted_at IS NULL OR deleted_at='')", user_id),
        "videos": ("SELECT COUNT(*) FROM videos WHERE user_id=? AND (deleted_at IS NULL OR deleted_at='')", user_id),
    }
    history_totals = {name: _scalar(conn, sql, (param,)) for name, (sql, param) in total_queries.items()}
    history_totals.update(login_attempts=int(access["attempts"] or 0), sessions=int(counts["sessions"] or 0), session_events=int(counts["session_events"] or 0))
    return {
        "access_summary": {"login_attempts": int(access["attempts"] or 0), "successful_logins": int(access["successful"] or 0), "failed_logins": int(access["failed"] or 0), "first_success_at": access["first_success_at"], "last_success_at": access["last_success_at"], "unique_ips": len(ips), "sessions": int(counts["sessions"] or 0), "active_sessions": int(counts["active_sessions"] or 0), "devices": int(counts["devices"] or 0), "session_events": int(counts["session_events"] or 0)},
        "ip_history": [{"ip_address": row["ip"], "first_seen_at": row["first_seen_at"], "last_seen_at": row["last_seen_at"], "seen_count": int(row["seen_count"] or 0), "successful_logins": int(row["successful_logins"] or 0), "failed_logins": int(row["failed_logins"] or 0), "sources": str(row["sources"] or "").split(",")} for row in ips],
        "client_history": client_history,
        "model_usage": sorted(models.values(), key=lambda item: (-int(item["total"]), str(item["model"]))),
        "history_totals": history_totals,
        "activity_series": _user_activity_series(conn, internal_user_id, user_id),
        **_finance_projection(conn, internal_user_id, user_id),
    }


def user_history_page(conn: sqlite3.Connection, internal_user_id: str, section: str, limit: int, offset: int) -> dict[str, Any]:
    allowed = {"logins", "sessions", "events", "security", "audits", "generations", "media", "finance"}
    if section not in allowed:
        raise ValueError("unknown_section")
    user = conn.execute("SELECT id FROM users WHERE internal_user_id=?", (internal_user_id,)).fetchone()
    if user is None:
        raise LookupError("user_not_found")
    user_id = user["id"]
    if section == "logins":
        total = _scalar(conn, "SELECT COUNT(*) FROM auth_login_attempts WHERE internal_user_id=?", (internal_user_id,))
        rows = conn.execute("SELECT id,provider,identifier,success,failure_reason,ip_address,platform,created_at FROM auth_login_attempts WHERE internal_user_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?", (internal_user_id, limit, offset)).fetchall()
        items = [{"id": _short(r["id"]), "provider": r["provider"], "identifier": _text(r["identifier"], 160), "success": bool(r["success"]), "failure_reason": _text(r["failure_reason"], 240), "ip_address": r["ip_address"], "platform": r["platform"], "created_at": r["created_at"]} for r in rows]
    elif section == "sessions":
        total = _scalar(conn, "SELECT COUNT(*) FROM auth_sessions WHERE internal_user_id=?", (internal_user_id,))
        rows = conn.execute("SELECT id,provider,platform,ip_address,created_at,last_seen_at,expires_at,revoked_at,revoke_reason,metadata_json FROM auth_sessions WHERE internal_user_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?", (internal_user_id, limit, offset)).fetchall()
        items = [{"id": _short(r["id"]), "provider": r["provider"], "platform": r["platform"], "ip_address": r["ip_address"], "created_at": r["created_at"], "last_seen_at": r["last_seen_at"], "expires_at": r["expires_at"], "revoked_at": r["revoked_at"], "revoke_reason": _text(r["revoke_reason"], 240), "device": _device(r["metadata_json"])} for r in rows]
    elif section == "events":
        total = _scalar(conn, "SELECT COUNT(*) FROM event_logs WHERE internal_user_id=?", (internal_user_id,))
        rows = conn.execute(
            "SELECT e.id,e.event_name,e.platform,e.device_type,e.ip_address,e.properties_json,e.created_at,"
            "s.metadata_json session_metadata_json FROM event_logs e "
            "LEFT JOIN auth_sessions s ON s.id=e.session_id "
            "WHERE e.internal_user_id=? ORDER BY e.created_at DESC LIMIT ? OFFSET ?",
            (internal_user_id, limit, offset),
        ).fetchall()
        items = []
        for r in rows:
            device = _device(r["session_metadata_json"])
            items.append({
                "id": _short(r["id"]),
                "event_name": r["event_name"],
                "platform": r["platform"],
                "device_type": r["device_type"] or device.get("device_type"),
                "browser": device.get("browser"),
                "os": device.get("os"),
                "ip_address": r["ip_address"],
                "details": _event_details(r["properties_json"]),
                "created_at": r["created_at"],
            })
    elif section == "security":
        total = _scalar(conn, "SELECT COUNT(*) FROM security_events WHERE internal_user_id=?", (internal_user_id,))
        rows = conn.execute("SELECT id,severity,event_type,ip_address,details_json,created_at FROM security_events WHERE internal_user_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?", (internal_user_id, limit, offset)).fetchall()
        items = [{"id": _short(r["id"]), "severity": r["severity"], "event_type": r["event_type"], "ip_address": r["ip_address"], "details": _event_details(r["details_json"]), "created_at": r["created_at"]} for r in rows]
    elif section == "audits":
        total = _scalar(conn, "SELECT COUNT(*) FROM audit_logs WHERE target_internal_user_id=?", (internal_user_id,))
        rows = conn.execute("SELECT id,action,entity_type,entity_id,actor_internal_user_id,ip_address,after_json,created_at FROM audit_logs WHERE target_internal_user_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?", (internal_user_id, limit, offset)).fetchall()
        items = [{"id": _short(r["id"]), "action": r["action"], "entity_type": r["entity_type"], "entity_id": _short(r["entity_id"]), "actor": _short(r["actor_internal_user_id"]), "ip_address": r["ip_address"], "reason": _text(_event_details(r["after_json"]).get("reason"), 240), "created_at": r["created_at"]} for r in rows]
    elif section == "generations":
        total = _scalar(conn, "SELECT COUNT(*) FROM jobs WHERE user_id=?", (user_id,))
        rows = conn.execute("SELECT id,mode,provider,status,prompt_original,error_message,settings_json,created_at,started_at,completed_at FROM jobs WHERE user_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?", (user_id, limit, offset)).fetchall()
        job_tokens = _token_job_map(conn, user_id)
        calibration = _video_cost_calibration(conn)
        image_by_job: dict[str, sqlite3.Row] = {}
        for media_row in conn.execute(
            "SELECT id,job_id,width,height FROM images WHERE user_id=? AND job_id IS NOT NULL "
            "AND (deleted_at IS NULL OR deleted_at='') ORDER BY created_at DESC",
            (user_id,),
        ):
            image_by_job.setdefault(str(media_row["job_id"]), media_row)
        video_by_job: dict[str, sqlite3.Row] = {}
        for media_row in conn.execute(
            "SELECT id,job_id,width,height,duration_seconds FROM videos WHERE user_id=? "
            "AND (deleted_at IS NULL OR deleted_at='') ORDER BY created_at DESC",
            (user_id,),
        ):
            video_by_job.setdefault(str(media_row["job_id"]), media_row)
        items = []
        for r in rows:
            settings = _json_object(r["settings_json"])
            tokens = job_tokens.get(str(r["id"]), {"main": 0, "daily": 0, "refunded": 0})
            preview = video_by_job.get(str(r["id"])) or image_by_job.get(str(r["id"]))
            preview_type = "video" if str(r["id"]) in video_by_job else ("image" if preview else None)
            preview_id = preview["id"] if preview else None
            elapsed = _elapsed_seconds(r["started_at"] or r["created_at"], r["completed_at"])
            items.append({"id": _short(r["id"]), "job_id": r["id"], "mode": r["mode"], "provider": r["provider"], "provider_kind": "local" if r["provider"] == "comfyui" else "api", "status": r["status"], "model": settings.get("modelProfile") or settings.get("openrouterModel") or settings.get("model") or r["provider"], "prompt": _text(r["prompt_original"], 3000), "error": _text(r["error_message"], 600), "created_at": r["created_at"], "started_at": r["started_at"], "completed_at": r["completed_at"], "elapsed_seconds": elapsed, "tokens": {**tokens, "net": max(0, int(tokens["main"]) + int(tokens["daily"]) - int(tokens["refunded"]))}, "preview_type": preview_type, "preview_url": f"/api/admin/media/{preview_type}/{preview_id}" + ("?variant=thumb" if preview_type == "image" else "") if preview_type and preview_id else None, "preview_width": preview["width"] if preview else None, "preview_height": preview["height"] if preview else None, **_generation_economics(settings, r["status"], provider=r["provider"], mode=r["mode"], elapsed_seconds=elapsed, cost_multiplier=calibration.get(_video_cost_key(settings, r["mode"]), 1.0)), "settings": {key: settings[key] for key in ("aspectRatio", "resolution", "quality", "duration", "steps", "seed") if settings.get(key) is not None}})
    elif section == "finance":
        items = []
        for r in conn.execute("SELECT id,invoice_code,status,currency,total_amount,tokens_total,reason,created_at,issued_at,paid_at,cancelled_at,refunded_at FROM invoices WHERE internal_user_id=?", (internal_user_id,)):
            items.append({"kind": "invoice", "id": _short(r["id"]), "code": r["invoice_code"], "status": r["status"], "currency": r["currency"], "amount": int(r["total_amount"] or 0), "tokens": int(r["tokens_total"] or 0), "reason": _text(r["reason"], 240), "created_at": r["created_at"], "issued_at": r["issued_at"], "paid_at": r["paid_at"], "cancelled_at": r["cancelled_at"], "refunded_at": r["refunded_at"]})
        for r in conn.execute("SELECT id,invoice_id,status,amount,currency,method,provider,paid_at,reason,token_ledger_id,created_at FROM payments WHERE internal_user_id=?", (internal_user_id,)):
            items.append({"kind": "payment", "id": _short(r["id"]), "invoice_id": _short(r["invoice_id"]), "status": r["status"], "amount": int(r["amount"] or 0), "currency": r["currency"], "method": r["method"], "provider": r["provider"], "paid_at": r["paid_at"], "reason": _text(r["reason"], 240), "tokens_credited": bool(r["token_ledger_id"]), "token_ledger_id": _short(r["token_ledger_id"]), "created_at": r["created_at"]})
        for r in conn.execute("SELECT id,payment_id,invoice_id,status,amount,currency,reason,token_reversal_ledger_id,created_at,completed_at FROM refunds WHERE internal_user_id=?", (internal_user_id,)):
            items.append({"kind": "refund", "id": _short(r["id"]), "payment_id": _short(r["payment_id"]), "invoice_id": _short(r["invoice_id"]), "status": r["status"], "amount": int(r["amount"] or 0), "currency": r["currency"], "reason": _text(r["reason"], 240), "tokens_reversed": bool(r["token_reversal_ledger_id"]), "created_at": r["created_at"], "completed_at": r["completed_at"]})
        for r in conn.execute("SELECT id,delta,reason,meta_json,created_at FROM token_ledger WHERE user_id=?", (user_id,)):
            metadata = _json_object(r["meta_json"])
            items.append({"kind": "token", "id": _short(r["id"]), "status": "completed", "delta": int(r["delta"] or 0), "reason": r["reason"], "job_id": _short(metadata.get("jobId") or metadata.get("job_id")), "daily_part": int(metadata.get("daily_part") or 0), "main_part": int(metadata.get("balance_part") or 0), "token_cost": int(metadata.get("token_cost") or 0), "created_at": r["created_at"]})
        items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        total = len(items)
        items = items[offset:offset + limit]
    else:
        image_total = _scalar(conn, "SELECT COUNT(*) FROM images WHERE user_id=? AND (deleted_at IS NULL OR deleted_at='')", (user_id,))
        video_total = _scalar(conn, "SELECT COUNT(*) FROM videos WHERE user_id=? AND (deleted_at IS NULL OR deleted_at='')", (user_id,))
        source_total = _scalar(conn, "SELECT COUNT(*) FROM image_sources WHERE user_id=? AND (library_deleted_at IS NULL OR library_deleted_at='')", (user_id,)) + _scalar(conn, "SELECT COUNT(*) FROM video_sources WHERE user_id=?", (user_id,))
        total = image_total + video_total + source_total
        rows = conn.execute(
            "SELECT media_type,id,job_id,mode,provider,prompt_original,width,height,duration_seconds,settings_json,stored_bytes,is_favorite,created_at,source_kind,source_role,slot_index,parent_id FROM ("
            "SELECT 'image' media_type,id,job_id,mode,provider,prompt_original,width,height,NULL duration_seconds,settings_json,stored_bytes,is_favorite,created_at,NULL source_kind,NULL source_role,NULL slot_index,NULL parent_id FROM images WHERE user_id=? AND (deleted_at IS NULL OR deleted_at='') "
            "UNION ALL SELECT 'video',id,job_id,mode,provider,prompt_original,width,height,duration_seconds,settings_json,stored_bytes,is_favorite,created_at,NULL,NULL,NULL,NULL FROM videos WHERE user_id=? AND (deleted_at IS NULL OR deleted_at='') "
            "UNION ALL SELECT 'source',s.id,i.job_id,'source_input',s.source_kind,NULL,s.thumb_width,s.thumb_height,NULL,'{}',s.thumb_bytes,s.is_favorite,s.created_at,s.source_kind,s.role,s.slot_index,s.image_id FROM image_sources s LEFT JOIN images i ON i.id=s.image_id WHERE s.user_id=? AND (s.library_deleted_at IS NULL OR s.library_deleted_at='') "
            "UNION ALL SELECT 'source',s.id,s.job_id,'source_input',s.source_kind,NULL,s.thumb_width,s.thumb_height,NULL,'{}',s.thumb_bytes,0,s.created_at,s.source_kind,s.role,s.slot_index,s.job_id FROM video_sources s WHERE s.user_id=?) "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (user_id, user_id, user_id, user_id, limit, offset),
        ).fetchall()
        publications: dict[tuple[str, str], dict[str, Any]] = {}
        for publication in conn.execute(
            "SELECT id,media_type,image_id,video_id,title,status,created_at FROM feed_publications "
            "WHERE internal_user_id=? ORDER BY created_at DESC",
            (internal_user_id,),
        ):
            media_id = publication["video_id"] if publication["media_type"] == "video" else publication["image_id"]
            if media_id:
                publications[(str(publication["media_type"]), str(media_id))] = {
                    "id": _short(publication["id"]),
                    "title": _text(publication["title"], 240),
                    "status": publication["status"],
                    "created_at": publication["created_at"],
                }
        items = []
        for r in rows:
            settings = _json_object(r["settings_json"])
            media_type = str(r["media_type"])
            media_route_type = "image" if media_type == "source" else media_type
            url = f"/api/admin/media/{media_route_type}/{r['id']}" + ("?variant=thumb" if media_route_type == "image" else "")
            full_url = f"/api/admin/media/{media_route_type}/{r['id']}" + ("?variant=full" if media_type == "image" else "?variant=thumb" if media_type == "source" else "")
            items.append({"type": media_type, "id": _short(r["id"]), "admin_media_id": r["id"], "job_id": _short(r["job_id"]), "media_url": url, "full_url": full_url, "mode": r["mode"], "provider": r["provider"], "model": settings.get("modelProfile") or settings.get("openrouterModel") or settings.get("model") or r["provider"], "prompt": _text(r["prompt_original"], 1200), "width": r["width"], "height": r["height"], "duration_seconds": r["duration_seconds"], "stored_bytes": int(r["stored_bytes"] or 0), "favorite": bool(r["is_favorite"]), "source_kind": r["source_kind"], "source_role": r["source_role"], "slot_index": r["slot_index"], "parent_id": _short(r["parent_id"]), "publication": publications.get((media_type, str(r["id"]))), "created_at": r["created_at"]})
    return {"ok": True, "section": section, "items": items, "total": total, "limit": limit, "offset": offset, "has_more": offset + len(items) < total}


def register_user_history_route(app: Any, db_factory: Callable[..., Any], require_admin: Callable[[Request], Any]) -> None:
    @app.get("/api/admin/users/{internal_user_id}/history-v2")
    async def admin_user_history_v2(internal_user_id: str, request: Request, section: str = "logins", limit: int = 50, offset: int = 0) -> dict[str, Any]:
        require_admin(request)
        try:
            with db_factory() as conn:
                return user_history_page(conn, internal_user_id, section, max(1, min(int(limit), 100)), max(0, int(offset)))
        except ValueError as exc:
            raise HTTPException(400, "Unknown history section.") from exc
        except LookupError as exc:
            raise HTTPException(404, "User not found.") from exc
