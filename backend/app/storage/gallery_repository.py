"""Read-only SQLite boundary for gallery quota and eviction candidates."""

from __future__ import annotations

from typing import Any, Protocol


class GalleryConnection(Protocol):
    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> Any: ...


def count_active_gallery_images(conn: GalleryConnection, user_id: str) -> int:
    """Count active owner rows, including the legacy empty deletion marker."""
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM images "
        "WHERE user_id = ? AND (deleted_at IS NULL OR deleted_at = '')",
        (user_id,),
    ).fetchone()
    return int(row["c"])


def select_gallery_eviction_candidates(
    conn: GalleryConnection,
    user_id: str,
    *,
    limit: int,
) -> list[Any]:
    """Return oldest owner rows not protected by the image's own favorite flag."""
    candidate_limit = int(limit)
    if candidate_limit <= 0:
        return []
    return list(
        conn.execute(
            """
            SELECT id, url, thumbnail_url FROM images
            WHERE user_id = ? AND is_favorite = 0 AND (deleted_at IS NULL OR deleted_at = '')
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            (user_id, candidate_limit),
        ).fetchall()
    )
