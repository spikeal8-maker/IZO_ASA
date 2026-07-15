"""Availability reconciliation is scoped and idempotent."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.storage.paths import local_media_path_from_url
from app.storage.recovery import (
    SourceAvailabilityRuntime,
    SourceRepairRuntime,
    reconcile_source_availability,
    repair_unavailable_sources_from_jobs,
)


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

    assert first == {"checked": 3, "available": 1, "missing": 2, "changed": 3}
    assert second == {"checked": 3, "available": 1, "missing": 2, "changed": 0}
    with connect() as conn:
        rows = {row["id"]: row for row in conn.execute("SELECT * FROM image_sources")}
    assert rows["present"]["availability_status"] == "available"
    assert rows["present"]["unavailable_at"] is None
    assert rows["missing"]["availability_status"] == "missing"
    assert rows["missing"]["unavailable_at"] is not None
    assert rows["library-deleted"]["availability_checked_at"] is None
    assert rows["deleted-image"]["availability_status"] == "missing"
    assert rows["deleted-image"]["availability_checked_at"] is not None


def test_source_repair_preserves_metadata_and_is_idempotent(tmp_path: Path):
    database = tmp_path / "repair.sqlite3"
    media = tmp_path / "media"
    media.mkdir()
    connect = _connect_factory(database)
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE jobs (id TEXT, settings_json TEXT);
            CREATE TABLE images (
                id TEXT, user_id TEXT, job_id TEXT, url TEXT, thumbnail_url TEXT
            );
            CREATE TABLE image_sources (
                id TEXT, image_id TEXT, user_id TEXT, source_image_id TEXT,
                slot_index INTEGER, thumb_url TEXT, thumb_width INTEGER,
                thumb_height INTEGER, thumb_bytes INTEGER, is_favorite INTEGER,
                availability_status TEXT, availability_checked_at TEXT,
                unavailable_at TEXT, created_at TEXT
            );
            INSERT INTO jobs VALUES ('job', '{"source": "candidate"}');
            INSERT INTO images VALUES ('image', 'owner', 'job', '', '');
            INSERT INTO image_sources VALUES (
                'stable-id', 'image', 'owner', NULL, 1, '/api/media/missing.webp',
                0, 0, 0, 1, 'missing', NULL, '2026-01-01', '2026-01-01'
            );
            """
        )

    def save_source_thumb(value: str, image_id: str, slot_index: int):
        assert (value, image_id, slot_index) == ("candidate", "image", 1)
        target = media / "repaired.webp"
        target.write_bytes(b"repaired")
        return target, 40, 30, target.stat().st_size

    runtime = SourceRepairRuntime(
        connect=connect,
        source_candidates_from_settings=lambda settings, slot: ["candidate"] if slot == 1 else [],
        save_source_thumb=save_source_thumb,
        public_url=lambda path, owner: f"/api/media/{path.name}?userId={owner}",
    )

    first = repair_unavailable_sources_from_jobs(runtime, "owner")
    second = repair_unavailable_sources_from_jobs(runtime, "owner")

    assert first == {"checked": 1, "repaired": 1, "unrecoverable": 0, "errors": 0}
    assert second == {"checked": 0, "repaired": 0, "unrecoverable": 0, "errors": 0}
    with connect() as conn:
        row = conn.execute("SELECT * FROM image_sources WHERE id = 'stable-id'").fetchone()
    assert row["id"] == "stable-id"
    assert row["is_favorite"] == 1
    assert row["availability_status"] == "available"
    assert row["unavailable_at"] is None
    assert row["thumb_url"] == "/api/media/repaired.webp?userId=owner"
    assert (row["thumb_width"], row["thumb_height"], row["thumb_bytes"]) == (40, 30, 8)
