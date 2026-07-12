"""Direct contracts for extracted private and public media services."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.storage.paths import resolve_under_root
from app.storage.private_media import (
    PrivateMediaAccessError,
    PrivateMediaRuntime,
    media_url_matches_filename,
    resolve_private_media,
)
from app.storage.public_media import (
    PublicMediaAccessError,
    PublicMediaRuntime,
    resolve_feed_media,
    resolve_public_avatar,
)


def _connect_factory(path: Path):
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def test_media_url_match_is_exact_except_for_query_string():
    assert media_url_matches_filename("/api/media/a.png?userId=ignored", "a.png") is True
    assert media_url_matches_filename("/media/a.png", "a.png") is True
    assert media_url_matches_filename("/api/media/a.png.evil", "a.png") is False
    assert media_url_matches_filename("/api/media/a.png/child", "a.png") is False


def test_private_media_requires_exact_cached_ownership(tmp_path: Path):
    database = tmp_path / "private.sqlite3"
    connect = _connect_factory(database)
    with connect() as conn:
        conn.execute("CREATE TABLE marker (id TEXT)")
    (tmp_path / "owned.png").write_bytes(b"owned")
    (tmp_path / "owned.png.evil").write_bytes(b"evil")
    cached = [{"userId": "owner", "url": "/api/media/owned.png?userId=owner"}]
    runtime = PrivateMediaRuntime(
        connect=connect,
        resolve_trusted_user=lambda request: {"legacy_user_id": "owner"},
        owner_exists=lambda conn, filename, user_id: False,
        cached_images=lambda: cached,
        resolve_path=resolve_under_root,
    )

    assert resolve_private_media(runtime, tmp_path, "owned.png", object()).name == "owned.png"
    with pytest.raises(PrivateMediaAccessError) as denied:
        resolve_private_media(runtime, tmp_path, "owned.png.evil", object())
    assert denied.value.status_code == 404
    with pytest.raises(PrivateMediaAccessError):
        resolve_private_media(runtime, tmp_path, "../outside.png", object())


def test_public_avatar_requires_current_database_reference(tmp_path: Path):
    database = tmp_path / "avatar.sqlite3"
    connect = _connect_factory(database)
    avatar_root = tmp_path / "avatars"
    avatar_root.mkdir()
    (avatar_root / "used.webp").write_bytes(b"used")
    (avatar_root / "orphan.webp").write_bytes(b"orphan")
    with connect() as conn:
        conn.execute("CREATE TABLE users (avatar_url TEXT)")
        conn.execute("INSERT INTO users VALUES ('/media/avatars/used.webp')")
    runtime = PublicMediaRuntime(connect=connect, resolve_path=resolve_under_root)

    assert resolve_public_avatar(runtime, avatar_root, "used.webp").name == "used.webp"
    with pytest.raises(PublicMediaAccessError) as orphan:
        resolve_public_avatar(runtime, avatar_root, "orphan.webp")
    assert orphan.value.status_code == 404


def test_feed_media_requires_published_ready_row_and_existing_file(tmp_path: Path):
    database = tmp_path / "feed.sqlite3"
    connect = _connect_factory(database)
    feed_dir = tmp_path / "feed"
    feed_dir.mkdir()
    (feed_dir / "thumb.webp").write_bytes(b"thumb")
    (feed_dir / "large.webp").write_bytes(b"large")
    with connect() as conn:
        conn.execute(
            "CREATE TABLE feed_publications "
            "(id TEXT, status TEXT, media_ready_at TEXT, feed_thumb_name TEXT, feed_large_name TEXT)"
        )
        conn.execute(
            "INSERT INTO feed_publications VALUES "
            "('published', 'published', '2026-01-01', 'feed/thumb.webp', 'feed/large.webp')"
        )
        conn.execute(
            "INSERT INTO feed_publications VALUES "
            "('hidden', 'hidden', '2026-01-01', 'feed/thumb.webp', 'feed/large.webp')"
        )
    runtime = PublicMediaRuntime(connect=connect, resolve_path=resolve_under_root)

    assert resolve_feed_media(runtime, tmp_path, "published", variant="large").name == "large.webp"
    assert resolve_feed_media(runtime, tmp_path, "published", thumb=1).name == "thumb.webp"
    with pytest.raises(PublicMediaAccessError) as hidden:
        resolve_feed_media(runtime, tmp_path, "hidden")
    assert hidden.value.status_code == 404
    with pytest.raises(PublicMediaAccessError) as bad_variant:
        resolve_feed_media(runtime, tmp_path, "published", variant="original")
    assert bad_variant.value.status_code == 400
