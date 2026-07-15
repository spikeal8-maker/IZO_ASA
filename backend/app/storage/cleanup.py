"""Non-destructive reconciliation of orphan image-source database rows."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourceCleanupRuntime:
    connect: Callable[[], sqlite3.Connection]
    filename_from_url: Callable[[str | None], str | None]


def reconcile_orphan_source_rows(
    runtime: SourceCleanupRuntime,
    media_root: Path,
    *,
    grace_seconds: int = 3600,
) -> dict[str, int]:
    """Delete rows whose parent is absent and report files for audited quarantine.

    Soft-deleted gallery parents are intentionally retained: their source
    snapshots form an independent user library and generation lineage. This
    function never deletes or moves a filesystem entry.
    """
    with runtime.connect() as conn:
        orphan_rows = conn.execute(
            """
            SELECT s.id, s.thumb_url
            FROM image_sources s
            LEFT JOIN images i ON i.id = s.image_id AND i.user_id = s.user_id
            WHERE i.id IS NULL
            """
        ).fetchall()
        orphan_names = {
            name
            for row in orphan_rows
            if (name := runtime.filename_from_url(str(row["thumb_url"] or "")))
        }
        if orphan_rows:
            conn.executemany("DELETE FROM image_sources WHERE id = ?", [(row["id"],) for row in orphan_rows])
        referenced = {
            name
            for row in conn.execute("SELECT thumb_url FROM image_sources").fetchall()
            if (name := runtime.filename_from_url(str(row["thumb_url"] or "")))
        }

    cutoff = time.time() - max(60, int(grace_seconds))
    aged_unreferenced = {
        path.name
        for path in media_root.glob("*_source*_*.webp")
        if path.name not in referenced and path.stat().st_mtime <= cutoff
    }
    candidates = orphan_names | aged_unreferenced
    return {
        "rows": len(orphan_rows),
        "fileCandidates": len(candidates),
        "rowFileCandidates": len(orphan_names),
        "rowFiles": 0,
        "files": 0,
    }
