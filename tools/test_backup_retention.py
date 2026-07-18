from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
TOOLS = ROOT / "tools"
for path in (BACKEND, TOOLS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import app.storage.backup as backup  # noqa: E402
from backup_transport import stage_snapshot  # noqa: E402
from prune_backup_snapshots import apply_plan, build_plan  # noqa: E402


def _database(path: Path) -> Path:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO sample(value) VALUES ('current')")
    return path


def _snapshot_ids(count: int, *, step: timedelta) -> list[str]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [(start + index * step).strftime("%Y%m%dT%H%M%S.%fZ") for index in range(count)]


def _create_snapshots(
    monkeypatch, database: Path, media: Path, backup_root: Path, snapshot_ids: list[str]
) -> None:
    iterator = iter(snapshot_ids)
    monkeypatch.setattr(backup, "_snapshot_id", lambda: next(iterator))
    for _snapshot_id in snapshot_ids:
        backup.create_backup(database, media, backup_root, require_separate_volume=False)


def test_reused_media_does_not_create_a_temporary_object(monkeypatch, tmp_path: Path) -> None:
    database = _database(tmp_path / "live.sqlite3")
    media = tmp_path / "media"
    media.mkdir()
    (media / "image.bin").write_bytes(b"unchanged-media")
    backup_root = tmp_path / "backup"
    ids = iter(_snapshot_ids(2, step=timedelta(hours=1)))
    monkeypatch.setattr(backup, "_snapshot_id", lambda: next(ids))

    backup.create_backup(database, media, backup_root, require_separate_volume=False)

    def fail_tempfile(*_args, **_kwargs):
        raise AssertionError("reused media must not be written to a temporary backup object")

    monkeypatch.setattr(backup.tempfile, "NamedTemporaryFile", fail_tempfile)
    result = backup.create_backup(database, media, backup_root, require_separate_volume=False)
    assert result.copied_objects == 0
    assert result.reused_objects == 1


def test_local_retention_deletes_only_old_snapshots_and_indexes(monkeypatch, tmp_path: Path) -> None:
    database = _database(tmp_path / "live.sqlite3")
    media = tmp_path / "media"
    media.mkdir()
    (media / "image.bin").write_bytes(b"shared-media-object")
    backup_root = tmp_path / "backup"
    snapshot_ids = _snapshot_ids(30, step=timedelta(hours=1))
    _create_snapshots(monkeypatch, database, media, backup_root, snapshot_ids)
    unrelated = backup_root / "DO_NOT_DELETE.txt"
    unrelated.write_text("keep", encoding="utf-8")
    media_objects_before = sorted(
        path.relative_to(backup_root) for path in (backup_root / "media-objects").rglob("*") if path.is_file()
    )

    plan = build_plan("local", backup_root, local_hourly=24, local_daily=14, local_weekly=8)
    assert plan.records[-1].snapshot_id == snapshot_ids[-1]
    assert plan.delete_records
    deleted = apply_plan(plan)

    assert deleted == [record.snapshot_id for record in plan.delete_records]
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert sorted(
        path.relative_to(backup_root) for path in (backup_root / "media-objects").rglob("*") if path.is_file()
    ) == media_objects_before
    assert (backup_root / "snapshots" / snapshot_ids[-1] / "COMPLETED").is_file()
    assert len(list((backup_root / "snapshots").iterdir())) == len(plan.keep_ids)


def test_cloud_retention_keeps_daily_and_monthly_snapshots(monkeypatch, tmp_path: Path) -> None:
    database = _database(tmp_path / "live.sqlite3")
    media = tmp_path / "media"
    media.mkdir()
    (media / "image.bin").write_bytes(b"cloud-media-object")
    backup_root = tmp_path / "backup"
    cloud_root = tmp_path / "cloud"
    snapshot_ids = _snapshot_ids(40, step=timedelta(days=1))
    _create_snapshots(monkeypatch, database, media, backup_root, snapshot_ids)
    for snapshot_id in snapshot_ids:
        stage_snapshot(backup_root, cloud_root, snapshot_id)
    unrelated = cloud_root / "README.txt"
    unrelated.write_text("keep", encoding="utf-8")
    media_objects_before = sorted(
        path.relative_to(cloud_root)
        for path in (cloud_root / "data" / "media-objects").rglob("*")
        if path.is_file()
    )

    plan = build_plan("cloud", cloud_root, cloud_daily=30, cloud_monthly=12)
    assert len(plan.keep_ids) == 30
    assert len(plan.delete_records) == 10
    apply_plan(plan)

    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert sorted(
        path.relative_to(cloud_root)
        for path in (cloud_root / "data" / "media-objects").rglob("*")
        if path.is_file()
    ) == media_objects_before
    assert (cloud_root / "database" / "snapshots" / snapshot_ids[-1] / "COMPLETED").is_file()
    assert len(list((cloud_root / "database" / "snapshots").iterdir())) == 30
