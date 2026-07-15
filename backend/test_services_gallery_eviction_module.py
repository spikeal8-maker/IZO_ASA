from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError

import pytest

import app.services.gallery_eviction as gallery_eviction_module
from app.services.gallery_eviction import GalleryEvictionRuntime, apply_gallery_evictions


def runtime(trace: list[tuple]) -> GalleryEvictionRuntime:
    return GalleryEvictionRuntime(
        soft_delete=lambda image_id: trace.append(("soft-delete", image_id)),
        delete_files=lambda url, thumbnail_url: trace.append(("files", url, thumbnail_url)),
        drop_cached_image=lambda image_id: trace.append(("cache", image_id)),
    )


def test_gallery_eviction_service_is_import_safe_and_has_no_concrete_io_dependencies() -> None:
    source = inspect.getsource(gallery_eviction_module).lower()

    for forbidden in (
        "import main",
        "fastapi",
        "pydantic",
        "sqlite3",
        "pathlib",
        "httpx",
        "os.environ",
        "unlink(",
    ):
        assert forbidden not in source


def test_runtime_is_frozen() -> None:
    configured = runtime([])

    with pytest.raises(FrozenInstanceError):
        configured.soft_delete = lambda _image_id: None  # type: ignore[misc]


def test_apply_evictions_preserves_row_and_side_effect_order() -> None:
    trace: list[tuple] = []
    rows = [
        {"id": "first", "url": "/first.webp", "thumbnail_url": "/first-thumb.webp"},
        {"id": "second", "url": "/second.webp", "thumbnail_url": "/second-thumb.webp"},
    ]

    removed = apply_gallery_evictions(runtime(trace), rows)

    assert removed == 2
    assert trace == [
        ("soft-delete", "first"),
        ("files", "/first.webp", "/first-thumb.webp"),
        ("cache", "first"),
        ("soft-delete", "second"),
        ("files", "/second.webp", "/second-thumb.webp"),
        ("cache", "second"),
    ]


def test_apply_evictions_forwards_nullable_media_values_without_normalization() -> None:
    trace: list[tuple] = []

    removed = apply_gallery_evictions(
        runtime(trace),
        [{"id": "image", "url": None, "thumbnail_url": None}],
    )

    assert removed == 1
    assert ("files", None, None) in trace


def test_empty_rows_return_zero_without_callbacks() -> None:
    trace: list[tuple] = []

    assert apply_gallery_evictions(runtime(trace), []) == 0
    assert trace == []


def test_callback_error_propagates_and_stops_current_and_remaining_rows() -> None:
    trace: list[tuple] = []

    def fail_soft_delete(image_id: str) -> None:
        trace.append(("soft-delete", image_id))
        raise RuntimeError("soft delete failed")

    configured = GalleryEvictionRuntime(
        soft_delete=fail_soft_delete,
        delete_files=lambda url, thumbnail_url: trace.append(("files", url, thumbnail_url)),
        drop_cached_image=lambda image_id: trace.append(("cache", image_id)),
    )
    rows = [
        {"id": "first", "url": "/first", "thumbnail_url": "/first-thumb"},
        {"id": "second", "url": "/second", "thumbnail_url": "/second-thumb"},
    ]

    with pytest.raises(RuntimeError, match="soft delete failed"):
        apply_gallery_evictions(configured, rows)

    assert trace == [("soft-delete", "first")]
