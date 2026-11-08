"""History-aware compaction of mutable private gallery originals."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable, MutableMapping
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from ..services.history_replay import history_policy_for_connection


@dataclass(frozen=True)
class GalleryMaintenanceRuntime:
    connect: Callable[[], sqlite3.Connection]
    local_path: Callable[[str], Path | None]
    public_url: Callable[[Path, str], str]
    media_filename: Callable[[str | None], str | None]
    cached_images: MutableMapping[str, dict[str, Any]]
    archive_max_side: int
    archive_quality: int


def _guard_image(runtime: GalleryMaintenanceRuntime, image_id: str) -> None:
    with closing(runtime.connect()) as conn:
        history_policy_for_connection(conn).require_allowed("images", image_id)


def _update_mutable(
    runtime: GalleryMaintenanceRuntime, image_id: str, user_id: str,
    assignments: str, values: tuple[Any, ...], condition: str = "",
) -> int:
    with closing(runtime.connect()) as conn, conn:
        allowed, parameters = history_policy_for_connection(conn).where_allowed("images", "id")
        return conn.execute(
            f"UPDATE images SET {assignments} WHERE id = ? AND user_id = ? "
            f"AND ({allowed}) {condition}",
            (*values, image_id, user_id, *parameters),
        ).rowcount


def _publish_archive(
    runtime: GalleryMaintenanceRuntime, row: Any, user_id: str, target: Path,
    size: tuple[int, int], before: int, after: int, now: str,
) -> bool:
    new_url = runtime.public_url(target, user_id)
    with closing(runtime.connect()) as conn:
        current = conn.execute("SELECT thumbnail_url FROM images WHERE id = ?", (row["id"],)).fetchone()
    thumbnail = current["thumbnail_url"] if current else None
    source_name = runtime.media_filename(str(row["url"] or ""))
    thumbnail_name = runtime.media_filename(thumbnail)
    new_thumbnail = new_url if source_name and thumbnail_name == source_name else thumbnail
    changed = _update_mutable(
        runtime, row["id"], user_id,
        "url = ?, thumbnail_url = ?, width = ?, height = ?, storage_tier = 'optimized', "
        "optimized_at = ?, original_bytes = ?, stored_bytes = ?",
        (new_url, new_thumbnail, *size, now, before, after),
        "AND storage_tier = 'optimizing'",
    )
    if changed:
        cached = runtime.cached_images.get(str(row["id"]))
        if cached is not None:
            cached.update(url=new_url, width=size[0], height=size[1], storageTier="optimized")
    return bool(changed)


def _compact_image(
    runtime: GalleryMaintenanceRuntime, row: Any, user_id: str, stats: dict[str, int],
) -> None:
    _guard_image(runtime, row["id"])
    source = runtime.local_path(str(row["url"] or ""))
    if source is None or not source.is_file():
        _update_mutable(runtime, row["id"], user_id, "storage_tier = 'missing'", ())
        stats["errors"] += 1
        return
    target = source.with_name(f"{source.stem}_archive.webp")
    temporary = source.with_name(f".{source.stem}_{uuid.uuid4().hex}.tmp.webp")
    try:
        before = source.stat().st_size
        with Image.open(source) as opened:
            prepared = ImageOps.exif_transpose(opened)
            if prepared.mode not in {"RGB", "RGBA"}:
                prepared = prepared.convert("RGB")
            prepared.thumbnail(
                (runtime.archive_max_side, runtime.archive_max_side), Image.Resampling.LANCZOS,
            )
            prepared.save(temporary, "WEBP", quality=runtime.archive_quality, method=6)
            size = prepared.size
        with Image.open(temporary) as verification:
            verification.verify()
        after = temporary.stat().st_size
        now = datetime.now(timezone.utc).isoformat()
        stats["bytes_before"] += before
        if after >= before:
            temporary.unlink(missing_ok=True)
            _update_mutable(
                runtime, row["id"], user_id,
                "storage_tier = 'checked', optimized_at = ?, original_bytes = ?, stored_bytes = ?",
                (now, before, before), "AND storage_tier = 'optimizing'",
            )
            stats["bytes_after"] += before
            return
        _guard_image(runtime, row["id"])
        temporary.replace(target)
        try:
            changed = _publish_archive(runtime, row, user_id, target, size, before, after, now)
            if not changed:
                _guard_image(runtime, row["id"])
                target.unlink(missing_ok=True)
                return
        except Exception:
            _guard_image(runtime, row["id"])
            target.unlink(missing_ok=True)
            raise
        _guard_image(runtime, row["id"])
        source.unlink(missing_ok=True)
        stats["optimized"] += 1
        stats["bytes_after"] += after
    except Exception:
        temporary.unlink(missing_ok=True)
        _update_mutable(
            runtime, row["id"], user_id, "storage_tier = 'original'", (),
            "AND storage_tier = 'optimizing'",
        )
        stats["errors"] += 1


def optimize_user_gallery(
    runtime: GalleryMaintenanceRuntime, user_id: str, *,
    keep_recent: int, limit: int | None = None,
) -> dict[str, int]:
    """Select, claim and compact only unsealed originals, preserving legacy mode."""
    stats = {"checked": 0, "optimized": 0, "bytes_before": 0, "bytes_after": 0, "errors": 0}
    fetch_limit = max(1, int(limit)) if limit is not None else 1_000_000
    with closing(runtime.connect()) as conn:
        allowed, parameters = history_policy_for_connection(conn).where_allowed("images", "id")
        ordered_rows = conn.execute(
            "SELECT id, url, storage_tier FROM images "
            f"WHERE user_id = ? AND deleted_at IS NULL AND ({allowed}) "
            "ORDER BY created_at DESC, id DESC",
            (user_id, *parameters),
        ).fetchall()
    rows = [
        row for row in ordered_rows[max(0, int(keep_recent)):]
        if str(row["storage_tier"] or "original") == "original"
    ][:fetch_limit]
    for row in rows:
        stats["checked"] += 1
        claimed = _update_mutable(
            runtime, row["id"], user_id, "storage_tier = 'optimizing'", (),
            "AND deleted_at IS NULL AND COALESCE(storage_tier, 'original') = 'original'",
        )
        if claimed:
            _compact_image(runtime, row, user_id, stats)
    return stats
