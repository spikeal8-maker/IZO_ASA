"""Source graph reads and repair decisions stay independent from FastAPI."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.storage.source_graph import (
    SourcePersistenceRuntime,
    SourceRowRepairRuntime,
    SourceTreeRuntime,
    read_image_source_tree,
    persist_image_source_rows,
    repair_image_source_rows_from_job,
)


def _connect_factory(path: Path):
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def test_source_tree_prefers_live_children_and_falls_back_to_snapshot(tmp_path: Path):
    database = tmp_path / "source-tree.sqlite3"
    connect = _connect_factory(database)
    snapshot = json.dumps([{"id": "snapshot-child"}])
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE image_sources (
                id TEXT, image_id TEXT, user_id TEXT, source_image_id TEXT,
                source_kind TEXT, role TEXT, slot_index INTEGER, thumb_url TEXT,
                thumb_width INTEGER, thumb_height INTEGER, thumb_bytes INTEGER,
                children_json TEXT, created_at TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO image_sources VALUES "
            "('root', 'result', 'owner', 'middle', 'gallery_image', 'base', 1, "
            "'/api/media/root.webp', 40, 30, 8, ?, '2026-01-02')",
            (snapshot,),
        )
        conn.execute(
            "INSERT INTO image_sources VALUES "
            "('live-child', 'middle', 'owner', NULL, 'upload', 'reference', 1, "
            "'/api/media/child.webp', 20, 10, 4, '[]', '2026-01-01')"
        )
    runtime = SourceTreeRuntime(
        load_json=lambda value: json.loads(value) if value else None,
        role_label=lambda role, slot: f"{role}:{slot}",
    )

    with connect() as conn:
        live = read_image_source_tree(runtime, conn, "result", "owner")
        conn.execute("DELETE FROM image_sources WHERE id = 'live-child'")
        fallback = read_image_source_tree(runtime, conn, "result", "owner")

    assert live[0]["roleLabel"] == "base:1"
    assert live[0]["children"][0]["id"] == "live-child"
    assert fallback[0]["children"] == [{"id": "snapshot-child"}]


def test_per_image_repair_is_owner_scoped_and_skips_existing_rows(tmp_path: Path):
    database = tmp_path / "source-repair.sqlite3"
    connect = _connect_factory(database)
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE images (
                id TEXT, user_id TEXT, job_id TEXT, created_at TEXT, deleted_at TEXT
            );
            CREATE TABLE jobs (id TEXT, user_id TEXT, settings_json TEXT);
            CREATE TABLE image_sources (
                id TEXT, image_id TEXT, user_id TEXT, source_image_id TEXT,
                source_kind TEXT, role TEXT, slot_index INTEGER, thumb_url TEXT,
                thumb_width INTEGER, thumb_height INTEGER, thumb_bytes INTEGER,
                children_json TEXT, created_at TEXT
            );
            INSERT INTO images VALUES
                ('existing', 'owner', 'job-existing', '2026-01-01', NULL),
                ('missing', 'owner', 'job-missing', '2026-01-02', NULL),
                ('deleted', 'owner', 'job-deleted', '2026-01-03', '2026-01-04');
            INSERT INTO jobs VALUES
                ('job-existing', 'owner', '{}'),
                ('job-missing', 'owner', '{"input": "candidate"}'),
                ('job-deleted', 'owner', '{"input": "deleted"}');
            INSERT INTO image_sources VALUES (
                'existing-source', 'existing', 'owner', NULL, 'upload', 'base', 1,
                '/api/media/existing.webp', 10, 10, 4, '[]', '2026-01-01'
            );
            """
        )
    restore_calls: list[tuple[str | None, str, str, str]] = []

    def restore(settings: str | None, image_id: str, user_id: str, created_at: str):
        restore_calls.append((settings, image_id, user_id, created_at))
        return [{"id": "restored-source", "imageId": image_id}]

    tree = SourceTreeRuntime(load_json=lambda value: json.loads(value) if value else None, role_label=lambda role, slot: str(role))
    runtime = SourceRowRepairRuntime(
        connect=connect,
        active_image_where="(deleted_at IS NULL OR deleted_at = '')",
        tree=tree,
        restore_from_job_settings=restore,
    )

    existing = repair_image_source_rows_from_job(runtime, "existing", "owner")
    repaired = repair_image_source_rows_from_job(runtime, "missing", "owner")
    wrong_owner = repair_image_source_rows_from_job(runtime, "missing", "other")
    deleted = repair_image_source_rows_from_job(runtime, "deleted", "owner")

    assert existing[0]["id"] == "existing-source"
    assert repaired == [{"id": "restored-source", "imageId": "missing"}]
    assert wrong_owner == []
    assert deleted == []
    assert restore_calls == [('{"input": "candidate"}', "missing", "owner", "2026-01-02")]


def _create_persistence_schema(connect) -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE image_sources (
                id TEXT, image_id TEXT, user_id TEXT, source_image_id TEXT,
                source_kind TEXT, role TEXT, slot_index INTEGER, thumb_url TEXT,
                thumb_width INTEGER, thumb_height INTEGER, thumb_bytes INTEGER,
                is_favorite INTEGER, library_deleted_at TEXT,
                availability_status TEXT, availability_checked_at TEXT,
                unavailable_at TEXT, children_json TEXT, created_at TEXT
            );
            INSERT INTO image_sources VALUES (
                'old-source', 'result', 'owner', NULL, 'upload', 'base', 1,
                '/api/media/old.webp?userId=owner', 10, 10, 3, 1, '2026-01-05',
                'available', NULL, NULL, '[]', '2026-01-01'
            );
            INSERT INTO image_sources VALUES (
                'parent-source', 'parent', 'owner', NULL, 'upload', 'reference', 1,
                '/api/media/parent.webp?userId=owner', 8, 8, 2, 0, NULL,
                'available', NULL, NULL, '[]', '2025-12-31'
            );
            """
        )


def _persistence_runtime(connect, media: Path, deleted: list[str]) -> SourcePersistenceRuntime:
    tree = SourceTreeRuntime(
        load_json=lambda value: json.loads(value) if value else None,
        role_label=lambda role, slot: f"{role}:{slot}",
    )

    def save_source_thumb(value: str, image_id: str, slot: int):
        target = media / f"{image_id}-{slot}.webp"
        target.write_bytes(b"new-thumb")
        return target, 40, 30, target.stat().st_size

    def delete_media_rel(name: str) -> None:
        with connect() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM image_sources WHERE image_id = 'result'"
            ).fetchone()[0] == 1
        deleted.append(name)

    return SourcePersistenceRuntime(
        connect=connect,
        tree=tree,
        save_source_thumb=save_source_thumb,
        find_source_image_id=lambda conn, value, owner: "parent" if value == "parent-url" else None,
        role_label=lambda role, slot, mode: f"{mode}:{role}:{slot}",
        public_url=lambda path, owner: f"/api/media/{path.name}?userId={owner}",
        media_filename_from_url=lambda url: url.split("/api/media/", 1)[-1].split("?", 1)[0],
        delete_media_rel=delete_media_rel,
    )


def test_source_persistence_preserves_library_state_and_cleans_old_file_after_commit(tmp_path: Path):
    database = tmp_path / "persist.sqlite3"
    media = tmp_path / "media"
    media.mkdir()
    connect = _connect_factory(database)
    _create_persistence_schema(connect)
    deleted: list[str] = []
    runtime = _persistence_runtime(connect, media, deleted)

    saved = persist_image_source_rows(
        runtime,
        "result",
        "owner",
        [{"slot": 1, "role": "base", "value": "parent-url"}],
        "2026-01-10",
        mode="image_to_image",
    )

    assert len(saved) == 1
    assert saved[0]["sourceImageId"] == "parent"
    assert saved[0]["children"][0]["id"] == "parent-source"
    assert saved[0]["roleLabel"] == "image_to_image:base:1"
    assert deleted == ["old.webp"]
    with connect() as conn:
        row = conn.execute("SELECT * FROM image_sources WHERE image_id = 'result'").fetchone()
    assert row["is_favorite"] == 1
    assert row["library_deleted_at"] == "2026-01-05"
    assert row["availability_status"] == "available"
    assert json.loads(row["children_json"])[0]["id"] == "parent-source"


def test_source_persistence_rolls_back_database_and_new_file_on_insert_error(tmp_path: Path):
    database = tmp_path / "persist-rollback.sqlite3"
    media = tmp_path / "media"
    media.mkdir()
    connect = _connect_factory(database)
    _create_persistence_schema(connect)
    with connect() as conn:
        conn.execute(
            "CREATE TRIGGER fail_result_source BEFORE INSERT ON image_sources "
            "WHEN NEW.image_id = 'result' BEGIN SELECT RAISE(ABORT, 'forced insert failure'); END"
        )
    deleted: list[str] = []
    runtime = _persistence_runtime(connect, media, deleted)

    with pytest.raises(sqlite3.IntegrityError, match="forced insert failure"):
        persist_image_source_rows(
            runtime,
            "result",
            "owner",
            [{"slot": 1, "role": "base", "value": "parent-url"}],
            "2026-01-10",
            mode="image_to_image",
        )

    with connect() as conn:
        row = conn.execute("SELECT id FROM image_sources WHERE image_id = 'result'").fetchone()
    assert row["id"] == "old-source"
    assert deleted == []
    assert not (media / "result-1.webp").exists()
