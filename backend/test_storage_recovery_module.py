"""Availability reconciliation is scoped and idempotent."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.storage.paths import local_media_path_from_url
from app.storage.recovery import SourceAvailabilityRuntime, reconcile_source_availability


def _connect_factory(path: Path):
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def test_source_availability_reconciliation_is_scoped_and_idempotent(tmp_path: Path):
    database = tmp_path / "availability.sqlite3"
    media = tmp_path / "media"
    media.mkdir()
    (media / "present.webp").write_bytes(b"present")
    connect = _connect_factory(database)
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE images (id TEXT, user_id TEXT, deleted_at TEXT);
            CREATE TABLE image_sources (
                id TEXT, image_id TEXT, user_id TEXT, thumb_url TEXT,
                availability_status TEXT, availability_checked_at TEXT,
                unavailable_at TEXT, library_deleted_at TEXT
            );
            INSERT INTO images VALUES
                ('active', 'owner', NULL),
                ('deleted', 'owner', '2026-01-01');
            INSERT INTO image_sources VALUES
                ('present', 'active', 'owner', '/api/media/present.webp', 'missing', NULL, 'old', NULL),
                ('missing', 'active', 'owner', '/api/media/missing.webp', 'available', NULL, NULL, NULL),
                ('library-deleted', 'active', 'owner', '/api/media/missing.webp', 'available', NULL, NULL, '2026-01-01'),
                ('deleted-image', 'deleted', 'owner', '/api/media/missing.webp', 'available', NULL, NULL, NULL);
            """
        )
    runtime = SourceAvailabilityRuntime(
        connect=connect,
        path_from_url=lambda url: local_media_path_from_url(media, url),
    )

    first = reconcile_source_availability(
        runtime,
        active_image_where="(deleted_at IS NULL OR deleted_at = '')",
    )
    second = reconcile_source_availability(
        runtime,
        active_image_where="(deleted_at IS NULL OR deleted_at = '')",
    )

    assert first == {"checked": 2, "available": 1, "missing": 1, "changed": 2}
    assert second == {"checked": 2, "available": 1, "missing": 1, "changed": 0}
    with connect() as conn:
        rows = {row["id"]: row for row in conn.execute("SELECT * FROM image_sources")}
    assert rows["present"]["availability_status"] == "available"
    assert rows["present"]["unavailable_at"] is None
    assert rows["missing"]["availability_status"] == "missing"
    assert rows["missing"]["unavailable_at"] is not None
    assert rows["library-deleted"]["availability_checked_at"] is None
    assert rows["deleted-image"]["availability_checked_at"] is None
