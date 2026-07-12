"""Idempotent storage availability reconciliation independent from FastAPI."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class SourceAvailabilityRuntime:
    connect: Callable[[], sqlite3.Connection]
    path_from_url: Callable[[str], Path | None]


def reconcile_source_availability(
    runtime: SourceAvailabilityRuntime,
    *,
    active_image_where: str,
    user_id: str | None = None,
) -> dict[str, int]:
    now = datetime.now(timezone.utc).isoformat()
    params: list[str] = []
    where = ["(s.library_deleted_at IS NULL OR s.library_deleted_at = '')"]
    if user_id:
        where.append("s.user_id = ?")
        params.append(user_id)
    with runtime.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT s.id, s.thumb_url, s.availability_status
            FROM image_sources s
            JOIN images i ON i.id = s.image_id AND i.user_id = s.user_id
            WHERE {' AND '.join(where)}
              AND {active_image_where.replace('deleted_at', 'i.deleted_at')}
            """,
            params,
        ).fetchall()

    updates: list[tuple[str, str, str | None, str]] = []
    available = missing = changed = 0
    for row in rows:
        path = runtime.path_from_url(str(row["thumb_url"] or ""))
        is_available = bool(path and path.is_file() and path.stat().st_size > 0)
        status = "available" if is_available else "missing"
        available += int(is_available)
        missing += int(not is_available)
        changed += int(str(row["availability_status"] or "unknown") != status)
        updates.append((status, now, None if is_available else now, str(row["id"])))
    if updates:
        with runtime.connect() as conn:
            conn.executemany(
                "UPDATE image_sources SET availability_status = ?, "
                "availability_checked_at = ?, unavailable_at = ? WHERE id = ?",
                updates,
            )
    return {"checked": len(rows), "available": available, "missing": missing, "changed": changed}
