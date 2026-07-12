"""Gallery source-tree reads and per-image row recovery."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourceTreeRuntime:
    load_json: Callable[[str | None], Any]
    role_label: Callable[[str | None, int], str]


@dataclass(frozen=True)
class SourceRowRepairRuntime:
    connect: Callable[[], sqlite3.Connection]
    active_image_where: str
    tree: SourceTreeRuntime
    restore_from_job_settings: Callable[[str | None, str, str, str], list[dict[str, Any]]]


def _optional_row_value(row: sqlite3.Row, key: str) -> Any:
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


def read_image_source_tree(
    runtime: SourceTreeRuntime,
    conn: sqlite3.Connection,
    image_id: str,
    user_id: str,
    *,
    depth: int = 3,
    visited: set[str] | None = None,
) -> list[dict[str, Any]]:
    visited = set(visited or set())
    if depth <= 0 or image_id in visited:
        return []
    visited.add(image_id)
    rows = conn.execute(
        """
        SELECT * FROM image_sources
        WHERE image_id = ? AND user_id = ?
        ORDER BY slot_index ASC, created_at ASC
        """,
        (image_id, user_id),
    ).fetchall()
    sources: list[dict[str, Any]] = []
    for row in rows:
        source_image_id = row["source_image_id"]
        snapshot_children = runtime.load_json(_optional_row_value(row, "children_json")) or []
        if not isinstance(snapshot_children, list):
            snapshot_children = []
        live_children = (
            read_image_source_tree(
                runtime,
                conn,
                source_image_id,
                user_id,
                depth=depth - 1,
                visited=visited,
            )
            if source_image_id
            else []
        )
        slot_index = int(row["slot_index"] or 0)
        sources.append(
            {
                "id": row["id"],
                "imageId": row["image_id"],
                "sourceImageId": source_image_id,
                "sourceKind": row["source_kind"],
                "role": row["role"],
                "roleLabel": runtime.role_label(row["role"], slot_index),
                "slotIndex": slot_index,
                "thumbUrl": row["thumb_url"],
                "width": int(row["thumb_width"] or 0),
                "height": int(row["thumb_height"] or 0),
                "bytes": int(row["thumb_bytes"] or 0),
                "children": live_children or snapshot_children,
            }
        )
    return sources


def repair_image_source_rows_from_job(
    runtime: SourceRowRepairRuntime,
    image_id: str,
    user_id: str,
) -> list[dict[str, Any]]:
    with runtime.connect() as conn:
        image = conn.execute(
            "SELECT id, user_id, job_id, created_at FROM images "
            f"WHERE id = ? AND user_id = ? AND {runtime.active_image_where}",
            (image_id, user_id),
        ).fetchone()
        if image is None:
            return []
        existing = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM image_sources WHERE image_id = ? AND user_id = ?",
                (image_id, user_id),
            ).fetchone()["c"]
        )
        if existing:
            return read_image_source_tree(runtime.tree, conn, image_id, user_id)
        job = conn.execute(
            "SELECT settings_json FROM jobs WHERE id = ? AND user_id = ?",
            (image["job_id"], user_id),
        ).fetchone()
    if job is None:
        return []
    return runtime.restore_from_job_settings(
        job["settings_json"],
        image_id,
        user_id,
        image["created_at"],
    )
