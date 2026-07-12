"""Idempotent storage availability reconciliation independent from FastAPI."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


SourceThumb = tuple[Path, int, int, int]


@dataclass(frozen=True)
class SourceAvailabilityRuntime:
    connect: Callable[[], sqlite3.Connection]
    path_from_url: Callable[[str], Path | None]


@dataclass(frozen=True)
class SourceRepairRuntime:
    connect: Callable[[], sqlite3.Connection]
    source_candidates_from_settings: Callable[[str | None, int], list[str]]
    save_source_thumb: Callable[[str, str, int], SourceThumb | None]
    public_url: Callable[[Path, str], str]


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


def repair_unavailable_sources_from_jobs(
    runtime: SourceRepairRuntime,
    user_id: str | None = None,
    *,
    limit: int = 500,
) -> dict[str, int]:
    """Restore missing source thumbnails without replacing metadata rows."""
    stats = {"checked": 0, "repaired": 0, "unrecoverable": 0, "errors": 0}
    where = ["s.availability_status IN ('missing', 'unavailable')"]
    params: list[object] = []
    if user_id:
        where.append("s.user_id = ?")
        params.append(user_id)
    params.append(max(1, int(limit)))
    with runtime.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT s.*, i.job_id, j.settings_json
            FROM image_sources s
            JOIN images i ON i.id = s.image_id AND i.user_id = s.user_id
            LEFT JOIN jobs j ON j.id = i.job_id
            WHERE {' AND '.join(where)}
            ORDER BY s.created_at ASC, s.slot_index ASC
            LIMIT ?
            """,
            params,
        ).fetchall()

    for row in rows:
        stats["checked"] += 1
        candidates: list[str] = []
        try:
            candidates.extend(
                runtime.source_candidates_from_settings(
                    row["settings_json"],
                    int(row["slot_index"] or 0),
                )
            )
        except Exception:
            pass
        if row["source_image_id"]:
            with runtime.connect() as conn:
                source_image = conn.execute(
                    "SELECT url, thumbnail_url FROM images WHERE id = ? AND user_id = ?",
                    (row["source_image_id"], row["user_id"]),
                ).fetchone()
            if source_image:
                candidates.extend(
                    [
                        str(source_image["url"] or ""),
                        str(source_image["thumbnail_url"] or ""),
                    ]
                )

        repaired = None
        for value in dict.fromkeys(candidate for candidate in candidates if candidate):
            repaired = runtime.save_source_thumb(
                value,
                row["image_id"],
                int(row["slot_index"] or 0),
            )
            if repaired is not None:
                break
        if repaired is None:
            stats["unrecoverable"] += 1
            continue

        path, width, height, byte_size = repaired
        now = datetime.now(timezone.utc).isoformat()
        try:
            with runtime.connect() as conn:
                conn.execute(
                    """
                    UPDATE image_sources
                    SET thumb_url = ?, thumb_width = ?, thumb_height = ?, thumb_bytes = ?,
                        availability_status = 'available', availability_checked_at = ?, unavailable_at = NULL
                    WHERE id = ? AND availability_status IN ('missing', 'unavailable')
                    """,
                    (
                        runtime.public_url(path, row["user_id"]),
                        width,
                        height,
                        byte_size,
                        now,
                        row["id"],
                    ),
                )
                changed = conn.execute("SELECT changes()").fetchone()[0]
            if not changed:
                path.unlink(missing_ok=True)
                continue
            stats["repaired"] += 1
        except Exception:
            path.unlink(missing_ok=True)
            stats["errors"] += 1
    return stats
