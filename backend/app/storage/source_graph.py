"""Gallery source-tree reads and per-image row recovery."""

from __future__ import annotations

import sqlite3
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
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


SourceThumb = tuple[Path, int, int, int]


@dataclass(frozen=True)
class SourcePersistenceRuntime:
    connect: Callable[[], sqlite3.Connection]
    tree: SourceTreeRuntime
    save_source_thumb: Callable[[str, str, int], SourceThumb | None]
    find_source_image_id: Callable[[sqlite3.Connection, str, str], str | None]
    role_label: Callable[[str | None, int, str | None], str]
    public_url: Callable[[Path, str], str]
    media_filename_from_url: Callable[[str], str | None]
    delete_media_rel: Callable[[str], None]


@dataclass(frozen=True)
class SourceDeletionRuntime:
    filename_from_url: Callable[[str | None], str | None]
    delete_media_rel: Callable[[str], None]


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


def persist_image_source_rows(
    runtime: SourcePersistenceRuntime,
    image_id: str,
    user_id: str,
    source_inputs: list[dict[str, Any]],
    created_at: str,
    *,
    mode: str | None = None,
) -> list[dict[str, Any]]:
    if not source_inputs:
        return []
    saved: list[dict[str, Any]] = []
    new_paths: list[Path] = []
    old_urls: list[str] = []
    try:
        with runtime.connect() as conn:
            old_rows = conn.execute(
                "SELECT slot_index, thumb_url, is_favorite, library_deleted_at "
                "FROM image_sources WHERE image_id = ?",
                (image_id,),
            ).fetchall()
            old_urls = [str(row["thumb_url"] or "") for row in old_rows]
            old_states = {
                int(row["slot_index"] or 0): (
                    int(row["is_favorite"] or 0),
                    row["library_deleted_at"],
                )
                for row in old_rows
            }
            conn.execute("DELETE FROM image_sources WHERE image_id = ?", (image_id,))
            for position, source in enumerate(source_inputs, start=1):
                slot = int(source.get("slot") or position)
                value = str(source.get("value") or "")
                thumb = runtime.save_source_thumb(value, image_id, slot)
                if thumb is None:
                    continue
                thumb_path, width, height, byte_size = thumb
                new_paths.append(thumb_path)
                role = str(source.get("role") or "")
                source_id = runtime.find_source_image_id(conn, value, user_id)
                children_snapshot = (
                    read_image_source_tree(
                        runtime.tree,
                        conn,
                        source_id,
                        user_id,
                        depth=2,
                        visited={image_id},
                    )
                    if source_id
                    else []
                )
                kind = "gallery_image" if source_id else ("upload" if value.startswith("data:image") else "media")
                old_favorite, old_deleted_at = old_states.get(slot, (0, None))
                source_row = {
                    "id": uuid.uuid4().hex,
                    "imageId": image_id,
                    "sourceImageId": source_id,
                    "sourceKind": kind,
                    "role": role,
                    "roleLabel": runtime.role_label(role, slot, mode),
                    "slotIndex": slot,
                    "thumbUrl": runtime.public_url(thumb_path, user_id),
                    "width": width,
                    "height": height,
                    "bytes": byte_size,
                    "children": children_snapshot,
                }
                conn.execute(
                    """
                    INSERT INTO image_sources
                        (id, image_id, user_id, source_image_id, source_kind, role, slot_index,
                         thumb_url, thumb_width, thumb_height, thumb_bytes, is_favorite,
                         library_deleted_at, availability_status, availability_checked_at,
                         unavailable_at, children_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'available', ?, NULL, ?, ?)
                    """,
                    (
                        source_row["id"],
                        image_id,
                        user_id,
                        source_id,
                        kind,
                        role,
                        slot,
                        source_row["thumbUrl"],
                        width,
                        height,
                        byte_size,
                        old_favorite,
                        old_deleted_at,
                        datetime.now(timezone.utc).isoformat(),
                        json.dumps(children_snapshot, ensure_ascii=False),
                        created_at,
                    ),
                )
                saved.append(source_row)
    except Exception:
        for path in new_paths:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        raise
    for url in old_urls:
        name = runtime.media_filename_from_url(url)
        if name:
            runtime.delete_media_rel(name)
    return saved


def delete_image_source_rows(
    runtime: SourceDeletionRuntime,
    conn: sqlite3.Connection,
    image_id: str,
) -> int:
    rows = conn.execute(
        "SELECT thumb_url FROM image_sources WHERE image_id = ?",
        (image_id,),
    ).fetchall()
    for row in rows:
        name = runtime.filename_from_url(row["thumb_url"])
        if name:
            runtime.delete_media_rel(name)
    conn.execute("DELETE FROM image_sources WHERE image_id = ?", (image_id,))
    return len(rows)
