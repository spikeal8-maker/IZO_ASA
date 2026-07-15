from __future__ import annotations

import sqlite3

import pytest

import main


@pytest.fixture
def gallery_db(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "gallery-repository-characterization.sqlite3")
    monkeypatch.setattr(main, "MEDIA", tmp_path / "media")
    main.MEDIA.mkdir()
    main.images.clear()
    main.init_db()
    return main.DB_PATH


def _insert_user(conn: sqlite3.Connection, user_id: str, *, plan: str = "mini") -> sqlite3.Row:
    conn.execute(
        "INSERT INTO users (id, internal_user_id, role, plan, language, created_at, last_login_at) "
        "VALUES (?, ?, 'user', ?, 'ru', '2026-01-01', '2026-01-01')",
        (user_id, f"iuid-{user_id}", plan),
    )
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def _insert_image(
    conn: sqlite3.Connection,
    image_id: str,
    user_id: str,
    created_at: str,
    *,
    favorite: int = 0,
    deleted_at: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO images (id, user_id, job_id, url, thumbnail_url, width, height, mode, provider, "
        "settings_json, is_favorite, created_at, deleted_at) "
        "VALUES (?, ?, ?, ?, ?, 512, 512, 'text_to_image', 'test', '{}', ?, ?, ?)",
        (
            image_id,
            user_id,
            f"job-{image_id}",
            f"/api/media/{image_id}.webp",
            f"/api/media/{image_id}-thumb.webp",
            favorite,
            created_at,
            deleted_at,
        ),
    )


def _protect_source(conn: sqlite3.Connection, image_id: str, source_user_id: str) -> None:
    conn.execute(
        "INSERT INTO image_sources (id, image_id, user_id, source_kind, slot_index, thumb_url, "
        "is_favorite, created_at) VALUES (?, ?, ?, 'upload', 1, ?, 1, '2026-01-01')",
        (f"source-{image_id}-{source_user_id}", image_id, source_user_id, f"/api/media/{image_id}-source.webp"),
    )


def test_quota_count_is_owner_scoped_and_accepts_legacy_empty_deleted_at(gallery_db) -> None:
    with main.db() as conn:
        owner = _insert_user(conn, "owner", plan="plus")
        _insert_user(conn, "override", plan="free")
        _insert_image(conn, "owner-null", "owner", "2026-01-01", deleted_at=None)
        _insert_image(conn, "owner-empty", "owner", "2026-01-02", deleted_at="")
        _insert_image(conn, "owner-deleted", "owner", "2026-01-03", deleted_at="2026-02-01")
        _insert_image(conn, "override-active", "override", "2026-01-01")

        owner_quota = main.gallery_quota_for_user(conn, owner)
        override_quota = main.gallery_quota_for_user(conn, owner, "override")

    assert owner_quota["plan"] == "plus"
    assert owner_quota["gallery_used"] == 2
    assert override_quota["plan"] == "plus"
    assert override_quota["gallery_used"] == 1


def test_eviction_selects_oldest_non_image_favorite_and_preserves_source_library(
    gallery_db,
    monkeypatch,
) -> None:
    deleted_files: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main,
        "delete_image_files_from_disk",
        lambda *, url, thumbnail_url: deleted_files.append((url, thumbnail_url)),
    )
    with main.db() as conn:
        _insert_user(conn, "owner")
        _insert_user(conn, "other")
        _insert_image(conn, "source-protected", "owner", "2026-01-01")
        _protect_source(conn, "source-protected", "owner")
        _insert_image(conn, "image-favorite", "owner", "2026-01-02", favorite=1)
        _insert_image(conn, "candidate-b", "owner", "2026-01-03")
        _insert_image(conn, "candidate-a", "owner", "2026-01-03")
        _protect_source(conn, "candidate-a", "other")
        _insert_image(conn, "foreign-oldest", "other", "2025-01-01")
        main.images.update({image_id: {"id": image_id} for image_id in ("source-protected", "candidate-a", "candidate-b")})

        removed = main.evict_gallery_images_for_new_save(
            conn,
            "owner",
            {"gallery_slots": 4, "gallery_used": 4},
            "2026-03-01",
        )
        rows = conn.execute(
            "SELECT id, deleted_at FROM images WHERE user_id = 'owner' ORDER BY id"
        ).fetchall()

    assert removed == 1
    assert deleted_files == [("/api/media/source-protected.webp", "/api/media/source-protected-thumb.webp")]
    assert {row["id"]: row["deleted_at"] for row in rows}["source-protected"] == "2026-03-01"
    assert "source-protected" not in main.images
    assert "candidate-b" in main.images


def test_over_limit_eviction_selects_exactly_two_oldest_candidates(gallery_db, monkeypatch) -> None:
    monkeypatch.setattr(main, "delete_image_files_from_disk", lambda **_kwargs: None)
    with main.db() as conn:
        _insert_user(conn, "owner")
        for position, image_id in enumerate(("first", "second", "third"), start=1):
            _insert_image(conn, image_id, "owner", f"2026-01-0{position}")
        removed = main.evict_gallery_images_for_new_save(
            conn,
            "owner",
            {"gallery_slots": 2, "gallery_used": 3},
            "2026-03-01",
        )

    assert removed == 2
    with main.db() as conn:
        rows = conn.execute("SELECT id, deleted_at FROM images WHERE user_id='owner' ORDER BY created_at").fetchall()
    assert [row["id"] for row in rows if row["deleted_at"]] == ["first", "second"]


def test_eviction_applies_each_row_in_soft_delete_file_cache_order(gallery_db, monkeypatch) -> None:
    trace: list[tuple] = []

    class TracingConnection:
        def __init__(self, conn: sqlite3.Connection) -> None:
            self.conn = conn

        def execute(self, sql: str, parameters=()):
            if sql.startswith("UPDATE images SET deleted_at"):
                trace.append(("soft-delete", parameters[1], parameters[0]))
            return self.conn.execute(sql, parameters)

    class TracingImages(dict):
        def pop(self, key, *args):
            trace.append(("cache", key))
            return super().pop(key, *args)

    monkeypatch.setattr(
        main,
        "delete_image_files_from_disk",
        lambda *, url, thumbnail_url: trace.append(("files", url, thumbnail_url)),
    )
    monkeypatch.setattr(main, "images", TracingImages({"first": {}, "second": {}}))
    with main.db() as conn:
        _insert_user(conn, "owner")
        _insert_image(conn, "first", "owner", "2026-01-01")
        _insert_image(conn, "second", "owner", "2026-01-02")
        removed = main.evict_gallery_images_for_new_save(
            TracingConnection(conn),
            "owner",
            {"gallery_slots": 1, "gallery_used": 2},
            "2026-03-01",
        )

    assert removed == 2
    assert trace == [
        ("soft-delete", "first", "2026-03-01"),
        ("files", "/api/media/first.webp", "/api/media/first-thumb.webp"),
        ("cache", "first"),
        ("soft-delete", "second", "2026-03-01"),
        ("files", "/api/media/second.webp", "/api/media/second-thumb.webp"),
        ("cache", "second"),
    ]


def test_legacy_source_delete_wrapper_is_removed_and_eviction_still_succeeds(gallery_db, monkeypatch) -> None:
    trace: list[tuple] = []
    assert not hasattr(main, "delete_image_source_files")
    monkeypatch.setattr(main, "delete_image_files_from_disk", lambda **_kwargs: trace.append(("files",)))
    main.images["first"] = {"id": "first"}
    with main.db() as conn:
        _insert_user(conn, "owner")
        _insert_image(conn, "first", "owner", "2026-01-01")
        removed = main.evict_gallery_images_for_new_save(
            conn,
            "owner",
            {"gallery_slots": 1, "gallery_used": 1},
            "2026-03-01",
        )
        deleted_at = conn.execute("SELECT deleted_at FROM images WHERE id = 'first'").fetchone()["deleted_at"]

    assert removed == 1
    assert trace == [("files",)]
    assert deleted_at == "2026-03-01"
    assert "first" not in main.images
