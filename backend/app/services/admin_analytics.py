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
    models: dict[tuple[str, str], dict[str, Any]] = {}
    for row in conn.execute("SELECT provider,status,settings_json,created_at FROM jobs WHERE user_id=?", (user_id,)):
        settings = _json_object(row["settings_json"])
        provider = str(row["provider"] or "—")
        model = str(settings.get("modelProfile") or settings.get("openrouterModel") or settings.get("model") or provider)
        item = models.setdefault((provider, model), {"provider": provider, "model": model, "total": 0, "completed": 0, "failed": 0, "last_used_at": None})
        item["total"] += 1
        if row["status"] == "completed": item["completed"] += 1
        if row["status"] == "failed": item["failed"] += 1
        item["last_used_at"] = max(filter(None, (item["last_used_at"], row["created_at"])), default=None)
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
    }


def user_history_page(conn: sqlite3.Connection, internal_user_id: str, section: str, limit: int, offset: int) -> dict[str, Any]:
    allowed = {"logins", "sessions", "events", "security", "audits", "generations", "media"}
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
        rows = conn.execute("SELECT id,event_name,platform,device_type,ip_address,created_at FROM event_logs WHERE internal_user_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?", (internal_user_id, limit, offset)).fetchall()
        items = [{key: (_short(r[key]) if key == "id" else r[key]) for key in r.keys()} for r in rows]
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
        items = []
        for r in rows:
            settings = _json_object(r["settings_json"])
            items.append({"id": _short(r["id"]), "mode": r["mode"], "provider": r["provider"], "status": r["status"], "model": settings.get("modelProfile") or settings.get("openrouterModel") or settings.get("model") or r["provider"], "prompt": _text(r["prompt_original"], 3000), "error": _text(r["error_message"], 600), "created_at": r["created_at"], "started_at": r["started_at"], "completed_at": r["completed_at"], "settings": {key: settings[key] for key in ("aspectRatio", "resolution", "quality", "duration", "steps", "seed") if settings.get(key) is not None}})
    else:
        image_total = _scalar(conn, "SELECT COUNT(*) FROM images WHERE user_id=? AND (deleted_at IS NULL OR deleted_at='')", (user_id,))
        video_total = _scalar(conn, "SELECT COUNT(*) FROM videos WHERE user_id=? AND (deleted_at IS NULL OR deleted_at='')", (user_id,))
        total = image_total + video_total
        rows = conn.execute("SELECT media_type,id,job_id,mode,provider,prompt_original,width,height,duration_seconds,is_favorite,created_at FROM (SELECT 'image' media_type,id,job_id,mode,provider,prompt_original,width,height,NULL duration_seconds,is_favorite,created_at FROM images WHERE user_id=? AND (deleted_at IS NULL OR deleted_at='') UNION ALL SELECT 'video',id,job_id,mode,provider,prompt_original,width,height,duration_seconds,is_favorite,created_at FROM videos WHERE user_id=? AND (deleted_at IS NULL OR deleted_at='')) ORDER BY created_at DESC LIMIT ? OFFSET ?", (user_id, user_id, limit, offset)).fetchall()
        items = [{"type": r["media_type"], "id": _short(r["id"]), "admin_media_id": r["id"], "job_id": _short(r["job_id"]), "media_url": f"/api/admin/media/{r['media_type']}/{r['id']}" + ("?variant=thumb" if r["media_type"] == "image" else ""), "full_url": f"/api/admin/media/{r['media_type']}/{r['id']}" + ("?variant=full" if r["media_type"] == "image" else ""), "mode": r["mode"], "provider": r["provider"], "prompt": _text(r["prompt_original"], 1200), "width": r["width"], "height": r["height"], "duration_seconds": r["duration_seconds"], "favorite": bool(r["is_favorite"]), "created_at": r["created_at"]} for r in rows]
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
