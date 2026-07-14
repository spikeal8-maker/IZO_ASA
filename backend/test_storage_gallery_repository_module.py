from __future__ import annotations

import inspect
import sqlite3

import app.storage.gallery_repository as gallery_repository_module
from app.storage.gallery_repository import (
    count_active_gallery_images,
    select_gallery_eviction_candidates,
)


def connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE images (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            url TEXT NOT NULL,
            thumbnail_url TEXT NOT NULL,
            is_favorite INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            deleted_at TEXT
        );
        CREATE TABLE image_sources (
            id TEXT PRIMARY KEY,
            image_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            is_favorite INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    return conn


def add_image(
    conn: sqlite3.Connection,
    image_id: str,
    user_id: str,
    created_at: str,
    *,
    favorite: int = 0,
    deleted_at: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO images (id, user_id, url, thumbnail_url, is_favorite, created_at, deleted_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            image_id,
            user_id,
            f"/api/media/{image_id}.webp",
            f"/api/media/{image_id}-thumb.webp",
            favorite,
            created_at,
            deleted_at,
        ),
    )


def test_gallery_repository_is_import_safe_and_has_no_application_or_filesystem_dependency() -> None:
    source = inspect.getsource(gallery_repository_module).lower()

    for forbidden in ("import main", "fastapi", "pydantic", "pathlib", "httpx", "os.environ"):
        assert forbidden not in source


def test_count_active_gallery_images_is_owner_scoped_and_keeps_legacy_empty_marker() -> None:
    conn = connection()
    add_image(conn, "null", "owner", "2026-01-01")
    add_image(conn, "empty", "owner", "2026-01-02", deleted_at="")
    add_image(conn, "deleted", "owner", "2026-01-03", deleted_at="2026-02-01")
    add_image(conn, "foreign", "other", "2026-01-01")

    assert count_active_gallery_images(conn, "owner") == 2
    assert count_active_gallery_images(conn, "other") == 1
    assert count_active_gallery_images(conn, "missing") == 0


def test_select_candidates_orders_by_created_at_then_id_and_returns_exact_media_fields() -> None:
    conn = connection()
    add_image(conn, "later", "owner", "2026-01-03")
    add_image(conn, "same-b", "owner", "2026-01-02")
    add_image(conn, "same-a", "owner", "2026-01-02")

    rows = select_gallery_eviction_candidates(conn, "owner", limit=2)

    assert [row["id"] for row in rows] == ["same-a", "same-b"]
    assert [tuple(row) for row in rows] == [
        ("same-a", "/api/media/same-a.webp", "/api/media/same-a-thumb.webp"),
        ("same-b", "/api/media/same-b.webp", "/api/media/same-b-thumb.webp"),
    ]


def test_select_candidates_excludes_deleted_image_favorite_and_same_owner_source_favorite() -> None:
    conn = connection()
    add_image(conn, "deleted", "owner", "2026-01-01", deleted_at="2026-02-01")
    add_image(conn, "image-favorite", "owner", "2026-01-02", favorite=1)
    add_image(conn, "source-favorite", "owner", "2026-01-03")
    conn.execute(
        "INSERT INTO image_sources (id, image_id, user_id, is_favorite) VALUES ('source', 'source-favorite', 'owner', 1)"
    )
    add_image(conn, "candidate", "owner", "2026-01-04")

    rows = select_gallery_eviction_candidates(conn, "owner", limit=10)

    assert [row["id"] for row in rows] == ["candidate"]


def test_foreign_source_favorite_does_not_protect_owner_image_and_foreign_image_is_never_selected() -> None:
    conn = connection()
    add_image(conn, "owner-image", "owner", "2026-01-01")
    conn.execute(
        "INSERT INTO image_sources (id, image_id, user_id, is_favorite) VALUES ('foreign-source', 'owner-image', 'other', 1)"
    )
    add_image(conn, "foreign-image", "other", "2025-01-01")

    rows = select_gallery_eviction_candidates(conn, "owner", limit=10)

    assert [row["id"] for row in rows] == ["owner-image"]


def test_non_positive_limit_returns_no_candidates() -> None:
    conn = connection()
    add_image(conn, "candidate", "owner", "2026-01-01")

    assert select_gallery_eviction_candidates(conn, "owner", limit=0) == []
    assert select_gallery_eviction_candidates(conn, "owner", limit=-1) == []
