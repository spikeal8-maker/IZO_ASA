"""Generation input validation reports typed errors without FastAPI."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from app.storage.input_validation import (
    MediaInputValidationError,
    MediaInputValidationRuntime,
    validate_owned_media_inputs,
)
from app.storage.paths import local_media_path_from_url, media_filename_from_url


ACTIVE = "(deleted_at IS NULL OR deleted_at = '')"


def _connect_factory(path: Path):
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def _runtime(tmp_path: Path) -> tuple[MediaInputValidationRuntime, Path, Callable[[], sqlite3.Connection]]:
    database = tmp_path / "validation.sqlite3"
    media = tmp_path / "media"
    media.mkdir()
    connect = _connect_factory(database)
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE images (
                id TEXT, user_id TEXT, url TEXT, thumbnail_url TEXT, deleted_at TEXT
            );
            CREATE TABLE image_sources (
                id TEXT, image_id TEXT, user_id TEXT, thumb_url TEXT,
                library_deleted_at TEXT
            );
            CREATE TABLE jobs (id TEXT, user_id TEXT, settings_json TEXT);
            """
        )
    runtime = MediaInputValidationRuntime(
        connect=connect,
        filename_from_url=lambda value: media_filename_from_url(media, value),
        resolve_local_media=lambda value: local_media_path_from_url(media, value),
        active_image_where=ACTIVE,
    )
    return runtime, media, connect


def test_image_source_and_job_references_are_allowed(tmp_path: Path):
    runtime, media, connect = _runtime(tmp_path)
    for name in ("image.png", "source.png", "job.png"):
        (media / name).write_bytes(name.encode("ascii"))
    with connect() as conn:
        conn.executescript(
            """
            INSERT INTO images VALUES
              ('owned-image', 'owner', '/api/media/image.png?userId=owner', '', NULL),
              ('source-parent', 'owner', '', '', NULL);
            INSERT INTO image_sources VALUES
              ('owned-source', 'source-parent', 'owner', '/api/media/source.png', NULL);
            INSERT INTO jobs VALUES
              ('owned-job', 'owner', '{"inputImage1":"/api/media/job.png?userId=owner"}');
            """
        )

    validate_owned_media_inputs(
        runtime,
        [
            ("inputImage1", "/api/media/image.png"),
            ("inputImage2", "/api/media/source.png"),
            ("inputImages[3]", "/api/media/job.png"),
            ("canvas", "data:image/png;base64,ignored"),
        ],
        "owner",
    )


def test_missing_file_reports_field_before_ownership_lookup(tmp_path: Path):
    runtime, _media, _connect = _runtime(tmp_path)

    with pytest.raises(MediaInputValidationError) as exc_info:
        validate_owned_media_inputs(runtime, [("maskImage", "/api/media/missing.png")], "owner")

    assert exc_info.value.code == "input_media_missing"
    assert exc_info.value.field == "maskImage"


def test_existing_but_unowned_file_reports_unavailable(tmp_path: Path):
    runtime, media, connect = _runtime(tmp_path)
    (media / "foo.png").write_bytes(b"foreign")
    with connect() as conn:
        conn.execute(
            "INSERT INTO images VALUES "
            "('collision', 'owner', '/api/media/xfoo.png', '', NULL)"
        )

    with pytest.raises(MediaInputValidationError) as exc_info:
        validate_owned_media_inputs(runtime, [("inputImage1", "/api/media/foo.png")], "owner")

    assert exc_info.value.code == "input_media_unavailable"
    assert exc_info.value.field == "inputImage1"
