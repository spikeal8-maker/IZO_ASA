"""Import-safe feed source-history query and mapping."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def feed_source_history_payload(
    connection: Any,
    image_id: str | None,
    *,
    load_children: Callable[[Any], Any],
    row_get: Callable[[Any, str], Any],
    role_label: Callable[[Any, int], str],
) -> list[dict[str, Any]]:
    if not image_id:
        return []
    rows = connection.execute(
        """
        SELECT source_kind, role, slot_index, thumb_url, thumb_width, thumb_height, children_json
        FROM image_sources
        WHERE image_id = ?
        ORDER BY slot_index ASC, created_at ASC
        """,
        (image_id,),
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        children = load_children(row_get(row, "children_json")) or []
        items.append({
            "kind": row_get(row, "source_kind"),
            "role": row_get(row, "role"),
            "roleLabel": role_label(row_get(row, "role"), int(row_get(row, "slot_index") or 0)),
            "slotIndex": int(row_get(row, "slot_index") or 0),
            "thumbUrl": row_get(row, "thumb_url"),
            "width": int(row_get(row, "thumb_width") or 0),
            "height": int(row_get(row, "thumb_height") or 0),
            "children": children if isinstance(children, list) else [],
        })
    return items
