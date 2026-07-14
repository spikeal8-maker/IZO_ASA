"""Injected orchestration for applying selected gallery evictions."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GalleryEvictionRuntime:
    delete_sources: Callable[[str], None]
    soft_delete: Callable[[str], None]
    delete_files: Callable[[str | None, str | None], None]
    drop_cached_image: Callable[[str], None]


def apply_gallery_evictions(
    runtime: GalleryEvictionRuntime,
    rows: Iterable[Any],
) -> int:
    """Apply selected rows in the legacy source/row/file/cache order."""
    removed = 0
    for row in rows:
        image_id = row["id"]
        runtime.delete_sources(image_id)
        runtime.soft_delete(image_id)
        runtime.delete_files(row["url"], row["thumbnail_url"])
        runtime.drop_cached_image(image_id)
        removed += 1
    return removed
