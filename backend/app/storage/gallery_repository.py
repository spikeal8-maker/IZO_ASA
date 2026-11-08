"""Read-only SQLite boundary for gallery quota and eviction candidates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from ..services.history_replay import history_policy_for_connection


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


def preserved_gallery_tariff(
    conn: GalleryConnection, user_id: str, tariff: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Reserve sealed active history separately from the ordinary new-work quota."""
    policy = history_policy_for_connection(conn)
    slots = int(tariff["gallery_slots"])
    if not policy.enabled or slots <= 0:
        return tariff
    allowed, parameters = policy.where_allowed("images", "id")
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM images WHERE user_id = ? "
        "AND (deleted_at IS NULL OR deleted_at = '') "
        f"AND NOT ({allowed})",
        (user_id, *parameters),
    ).fetchone()
    return {**tariff, "gallery_slots": slots + int(row["c"])}


def select_gallery_eviction_candidates(
    conn: GalleryConnection,
    user_id: str,
    *,
    limit: int,
) -> list[Any]:
    """Return oldest mutable owner rows not protected by their favorite flag."""
    candidate_limit = int(limit)
    if candidate_limit <= 0:
        return []
    allowed, parameters = history_policy_for_connection(conn).where_allowed("images", "id")
    return list(
        conn.execute(
            f"""
            SELECT id, url, thumbnail_url FROM images
            WHERE user_id = ? AND is_favorite = 0 AND (deleted_at IS NULL OR deleted_at = '')
              AND ({allowed})
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            (user_id, *parameters, candidate_limit),
        ).fetchall()
    )
