"""Compact heartbeat persistence for online-user analytics."""

from __future__ import annotations

import sqlite3
from datetime import datetime


def record_heartbeat(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    platform: str,
    seconds: int,
    now: datetime,
) -> None:
    now_iso = now.isoformat()
    bucket_at = now.replace(minute=(now.minute // 5) * 5, second=0, microsecond=0).isoformat()
    conn.execute(
        "UPDATE users SET total_time_seconds=total_time_seconds+?,last_seen_at=? WHERE id=?",
        (seconds, now_iso, user_id),
    )
    user = conn.execute("SELECT internal_user_id FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        return
    conn.execute(
        "INSERT INTO user_presence_samples "
        "(bucket_at,user_id,internal_user_id,platform,active_seconds,updated_at) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(bucket_at,user_id) DO UPDATE SET "
        "internal_user_id=COALESCE(excluded.internal_user_id,user_presence_samples.internal_user_id),"
        "platform=excluded.platform,"
        "active_seconds=MIN(300,user_presence_samples.active_seconds+excluded.active_seconds),"
        "updated_at=excluded.updated_at",
        (bucket_at, user_id, user["internal_user_id"], platform, min(300, seconds), now_iso),
    )
