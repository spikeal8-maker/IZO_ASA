"""Persist immutable thumbnails for video generation input lineage."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class VideoSourcePersistenceRuntime:
    connect: Callable[[], sqlite3.Connection]
    save_source_thumb: Callable[[str | None, str, int], tuple[Path, int, int, int] | None]
    find_source_image_id: Callable[[sqlite3.Connection, str | None, str], str | None]
    read_image_children: Callable[[sqlite3.Connection, str, str], list[dict[str, Any]]]
    public_url: Callable[[Path, str], str]


def generation_source_inputs(req: Any) -> list[dict[str, Any]]:
    inputs: list[dict[str, Any]] = []
    if req.firstFrame:
        inputs.append({
            "value": req.firstFrame,
            "role": "first_frame",
            "roleLabel": "Начальный кадр" if req.mode == "first_last_frame" else "Исходное изображение",
        })
    if req.lastFrame:
        inputs.append({"value": req.lastFrame, "role": "last_frame", "roleLabel": "Конечный кадр"})
    for index, value in enumerate(req.references, start=1):
        inputs.append({"value": value, "role": "reference", "roleLabel": f"Референс {index}"})
    return inputs


def persist_video_sources(
    runtime: VideoSourcePersistenceRuntime,
    job_id: str,
    user_id: str,
    source_inputs: list[dict[str, Any]],
    created_at: str,
) -> list[dict[str, Any]]:
    if not source_inputs:
        return []
    saved: list[dict[str, Any]] = []
    new_paths: list[Path] = []
    try:
        with runtime.connect() as conn:
            conn.execute("DELETE FROM video_sources WHERE job_id = ? AND user_id = ?", (job_id, user_id))
            for slot, source in enumerate(source_inputs, start=1):
                value = str(source["value"])
                thumb = runtime.save_source_thumb(value, job_id, slot)
                if thumb is None:
                    continue
                thumb_path, width, height, byte_size = thumb
                new_paths.append(thumb_path)
                source_image_id = runtime.find_source_image_id(conn, value, user_id)
                children = runtime.read_image_children(conn, source_image_id, user_id) if source_image_id else []
                source_kind = "gallery_image" if source_image_id else ("upload" if value.startswith("data:image") else "media")
                row = {
                    "id": uuid.uuid4().hex,
                    "jobId": job_id,
                    "sourceImageId": source_image_id,
                    "sourceKind": source_kind,
                    "role": source["role"],
                    "roleLabel": source["roleLabel"],
                    "slotIndex": slot,
                    "thumbUrl": runtime.public_url(thumb_path, user_id),
                    "width": width,
                    "height": height,
                    "bytes": byte_size,
                    "children": children,
                }
                conn.execute(
                    """
                    INSERT INTO video_sources
                        (id, job_id, user_id, source_image_id, source_kind, role, slot_index,
                         thumb_url, thumb_width, thumb_height, thumb_bytes, children_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"], job_id, user_id, source_image_id, source_kind, source["role"], slot,
                        row["thumbUrl"], width, height, byte_size,
                        json.dumps(children, ensure_ascii=False), created_at,
                    ),
                )
                saved.append(row)
            if saved:
                job = conn.execute("SELECT settings_json FROM jobs WHERE id = ? AND user_id = ?", (job_id, user_id)).fetchone()
                if job is not None:
                    try:
                        settings = json.loads(job["settings_json"] or "{}")
                    except (TypeError, ValueError, json.JSONDecodeError):
                        settings = {}
                    settings["sourceHistory"] = saved
                    conn.execute(
                        "UPDATE jobs SET settings_json = ? WHERE id = ? AND user_id = ?",
                        (json.dumps(settings, ensure_ascii=False), job_id, user_id),
                    )
        return saved
    except Exception:
        for path in new_paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
