"""Media reference ownership uses exact paths instead of filename substrings."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.storage.media_references import (
    find_owned_active_image,
    owned_active_source_exists,
    owned_job_media_reference_exists,
)


ACTIVE = "(deleted_at IS NULL OR deleted_at = '')"


def _connect_factory(path: Path):
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def _create_schema(connect) -> None:
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


def test_owned_image_match_is_exact_with_optional_query_and_legacy_path(tmp_path: Path):
    connect = _connect_factory(tmp_path / "images.sqlite3")
    _create_schema(connect)
    with connect() as conn:
        conn.executescript(
            """
            INSERT INTO images VALUES
              ('collision', 'owner', '/api/media/xfoo.png?userId=owner', '', NULL),
              ('canonical', 'owner', '/api/media/foo.png?userId=owner', '', NULL),
              ('legacy', 'owner', '/media/legacy.png', '', NULL),
              ('deleted', 'owner', '/api/media/deleted.png', '', '2026-01-01');
            """
        )
        assert find_owned_active_image(conn, "foo.png", "owner", active_image_where=ACTIVE)["id"] == "canonical"
        assert find_owned_active_image(conn, "legacy.png", "owner", active_image_where=ACTIVE)["id"] == "legacy"
        assert find_owned_active_image(conn, "deleted.png", "owner", active_image_where=ACTIVE) is None
        conn.execute("DELETE FROM images WHERE id = 'canonical'")
        assert find_owned_active_image(conn, "foo.png", "owner", active_image_where=ACTIVE) is None


def test_source_match_rejects_substrings_deleted_parents_and_library_deleted_rows(tmp_path: Path):
    connect = _connect_factory(tmp_path / "sources.sqlite3")
    _create_schema(connect)
    with connect() as conn:
        conn.executescript(
            """
            INSERT INTO images VALUES
              ('active', 'owner', '', '', NULL),
              ('deleted', 'owner', '', '', '2026-01-01');
            INSERT INTO image_sources VALUES
              ('collision', 'active', 'owner', '/api/media/xfoo.png', NULL),
              ('exact', 'active', 'owner', '/api/media/foo.png?userId=owner', NULL),
              ('deleted-parent', 'deleted', 'owner', '/api/media/deleted.png', NULL),
              ('library-deleted', 'active', 'owner', '/api/media/library.png', '2026-01-01');
            """
        )
        assert owned_active_source_exists(conn, "foo.png", "owner", active_image_where=ACTIVE) is True
        assert owned_active_source_exists(conn, "deleted.png", "owner", active_image_where=ACTIVE) is False
        assert owned_active_source_exists(conn, "library.png", "owner", active_image_where=ACTIVE) is False
        conn.execute("DELETE FROM image_sources WHERE id = 'exact'")
        assert owned_active_source_exists(conn, "foo.png", "owner", active_image_where=ACTIVE) is False


def test_job_reference_matches_exact_json_string_and_ignores_invalid_json(tmp_path: Path):
    connect = _connect_factory(tmp_path / "jobs.sqlite3")
    _create_schema(connect)
    with connect() as conn:
        conn.executescript(
            """
            INSERT INTO jobs VALUES
              ('collision', 'owner', '{"inputImage1":"/api/media/xfoo.png"}'),
              ('exact', 'owner', '{"nested":{"image":"/api/media/foo.png?userId=owner"}}'),
              ('legacy', 'owner', '{"image":"/media/legacy.png"}'),
              ('invalid', 'owner', '{broken json');
            """
        )
        assert owned_job_media_reference_exists(conn, "foo.png", "owner") is True
        assert owned_job_media_reference_exists(conn, "legacy.png", "owner") is True
        conn.execute("DELETE FROM jobs WHERE id = 'exact'")
        assert owned_job_media_reference_exists(conn, "foo.png", "owner") is False
