"""Read-only CRM analytics projections.

The customer product has two visible token accounts: the daily tariff allowance
and the main balance.  Admin projections keep those accounts separate and use a
single business-day boundary (Europe/Moscow, UTC+03:00) for all "today" values.
"""

from __future__ import annotations

import json
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
