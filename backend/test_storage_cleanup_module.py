"""Cleanup reconciliation removes metadata only; files require quarantine."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.storage.cleanup import SourceCleanupRuntime, reconcile_orphan_source_rows
from app.storage.paths import media_filename_from_url


def _connect_factory(path: Path):
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def test_orphan_source_reconciliation_never_deletes_files(tmp_path: Path):
    database = tmp_path / "cleanup.sqlite3"
    media = tmp_path / "media"
    media.mkdir()
    orphan_file = media / "orphan_source1_old.webp"
    active_file = media / "active_source1_keep.webp"
    orphan_file.write_bytes(b"orphan")
    active_file.write_bytes(b"active")
    connect = _connect_factory(database)
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE images (id TEXT, user_id TEXT, deleted_at TEXT);
            CREATE TABLE image_sources (id TEXT, image_id TEXT, user_id TEXT, thumb_url TEXT);
            INSERT INTO images VALUES ('active-image', 'owner', NULL);
            INSERT INTO image_sources VALUES
                ('active-source', 'active-image', 'owner', '/api/media/active_source1_keep.webp'),
                ('orphan-source', 'missing-image', 'owner', '/api/media/orphan_source1_old.webp');
            """
        )
    runtime = SourceCleanupRuntime(
        connect=connect,
        filename_from_url=lambda url: media_filename_from_url(media, url),
    )

    result = reconcile_orphan_source_rows(runtime, media, grace_seconds=60)

    assert result == {"rows": 1, "fileCandidates": 1, "rowFileCandidates": 1, "rowFiles": 0, "files": 0}
    assert orphan_file.is_file()
    assert active_file.is_file()
    with connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM image_sources WHERE id='orphan-source'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM image_sources WHERE id='active-source'").fetchone()[0] == 1


def test_source_of_soft_deleted_image_remains_in_independent_library(tmp_path: Path):
    database = tmp_path / "soft-deleted-parent.sqlite3"
    media = tmp_path / "media"
    media.mkdir()
    source_file = media / "kept_source.webp"
    source_file.write_bytes(b"source")
    connect = _connect_factory(database)
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE images (id TEXT, user_id TEXT, deleted_at TEXT);
            CREATE TABLE image_sources (id TEXT, image_id TEXT, user_id TEXT, thumb_url TEXT);
            INSERT INTO images VALUES ('deleted-image', 'owner', '2026-01-01');
            INSERT INTO image_sources VALUES
                ('kept-source', 'deleted-image', 'owner', '/api/media/kept_source.webp');
            """
        )
    runtime = SourceCleanupRuntime(
        connect=connect,
        filename_from_url=lambda url: media_filename_from_url(media, url),
    )

    result = reconcile_orphan_source_rows(runtime, media, grace_seconds=0)

    assert result == {"rows": 0, "fileCandidates": 0, "rowFileCandidates": 0, "rowFiles": 0, "files": 0}
    assert source_file.is_file()
    with connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM image_sources WHERE id='kept-source'").fetchone()[0] == 1
