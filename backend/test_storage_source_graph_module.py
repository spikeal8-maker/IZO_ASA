"""Source graph reads and repair decisions stay independent from FastAPI."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.storage.source_graph import (
    SourceRowRepairRuntime,
    SourceTreeRuntime,
    read_image_source_tree,
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
