"""Direct contracts for import-safe storage path helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.storage.paths import (
    StoragePathError,
    local_media_path_from_url,
    media_filename_from_url,
    public_media_url,
    resolve_under_root,
)


def test_media_url_parsing_supports_canonical_and_legacy_urls(tmp_path: Path):
    nested = tmp_path / "nested"
    nested.mkdir()
    image = nested / "image.webp"
    image.write_bytes(b"image")

    assert local_media_path_from_url(tmp_path, "/api/media/nested/image.webp?userId=ignored") == image
    assert local_media_path_from_url(tmp_path, "/media/nested/image.webp") == image
    assert media_filename_from_url(tmp_path, "/api/media/nested/image.webp?x=1") == "nested/image.webp"
    assert local_media_path_from_url(tmp_path, "https://example.test/image.webp") is None
    assert local_media_path_from_url(tmp_path, "/api/media/missing.webp") is None


def test_storage_paths_reject_traversal_and_absolute_names(tmp_path: Path):
    outside = tmp_path.parent / "outside.webp"
    outside.write_bytes(b"outside")

    with pytest.raises(StoragePathError):
        resolve_under_root(tmp_path, "../outside.webp")
    with pytest.raises(StoragePathError):
        local_media_path_from_url(tmp_path, "/api/media/../outside.webp")
    assert media_filename_from_url(tmp_path, "/media/../outside.webp") is None
    assert local_media_path_from_url(tmp_path, "/api/media/") is None


def test_local_media_path_requires_a_file(tmp_path: Path):
    directory = tmp_path / "directory"
    directory.mkdir()
    assert local_media_path_from_url(tmp_path, "/api/media/directory") is None


def test_public_media_url_keeps_compatibility_shape(tmp_path: Path):
    assert public_media_url(tmp_path / "result.png", "user-1") == "/api/media/result.png?userId=user-1"
