"""Injected orchestration for applying selected gallery evictions."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from .history_replay import HistoricalReplayBlocked, HistoryReplayConfigurationError


@dataclass(frozen=True)
class GalleryEvictionRuntime:
    soft_delete: Callable[[str], None]
    delete_files: Callable[[str | None, str | None], None]
    drop_cached_image: Callable[[str], None]
    history_guard: Callable[[str], None] | None = None
    history_guard_required: bool = False


def apply_gallery_evictions(
    runtime: GalleryEvictionRuntime,
    rows: Iterable[Any],
) -> int:
    """Recheck selected rows before either database or filesystem destruction."""
    if runtime.history_guard_required and runtime.history_guard is None:
        raise HistoryReplayConfigurationError("Gallery eviction history guard is required")
    removed = 0
    for row in rows:
        image_id = row["id"]
        try:
            if runtime.history_guard is not None:
                runtime.history_guard(image_id)
        except HistoricalReplayBlocked:
            continue
        runtime.soft_delete(image_id)
        try:
            if runtime.history_guard is not None:
                runtime.history_guard(image_id)
        except HistoricalReplayBlocked:
            continue
        runtime.delete_files(row["url"], row["thumbnail_url"])
        runtime.drop_cached_image(image_id)
        removed += 1
    return removed
