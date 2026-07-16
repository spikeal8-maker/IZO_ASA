from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
TOOLS = ROOT / "tools"
for path in (BACKEND, TOOLS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.storage.backup import BackupError, create_backup, verify_snapshot  # noqa: E402
from backup_transport import (  # noqa: E402
    read_role,
    receive_snapshot,
    stage_snapshot,
    verify_cloud_snapshot,
)


def source(tmp_path: Path) -> tuple[Path, Path, Path]:
    database = tmp_path / "source" / "live.sqlite3"
    media = tmp_path / "source" / "media"
    media.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        connection.execute("INSERT INTO users (name) VALUES ('backup-user')")
    (media / "one.webp").write_bytes(b"image-one")
    (media / "nested").mkdir()
    (media / "nested" / "two.png").write_bytes(b"image-two")
    backup_root = tmp_path / "local-backup"
    return database, media, backup_root


def test_stage_and_receive_are_verified_and_immutable(tmp_path: Path) -> None:
    database, media, backup_root = source(tmp_path)
    created = create_backup(database, media, backup_root, require_separate_volume=False)
    cloud_root = tmp_path / "yandex-transport"

    staged = stage_snapshot(backup_root, cloud_root)
    assert staged.snapshot_id == created.snapshot_id
    assert verify_cloud_snapshot(cloud_root, created.snapshot_id) == staged

    # Re-staging a completed snapshot verifies it without rewriting content.
    database_copy = cloud_root / "database" / "snapshots" / created.snapshot_id / "database.sqlite3"
    original_mtime = database_copy.stat().st_mtime_ns
    assert stage_snapshot(backup_root, cloud_root) == staged
    assert database_copy.stat().st_mtime_ns == original_mtime

    replica = tmp_path / "replica-cache"
    received = receive_snapshot(cloud_root, replica, created.snapshot_id)
    assert received == staged
    assert verify_snapshot(replica, created.snapshot_id) == received


def test_cloud_completed_is_published_last_and_tamper_is_detected(tmp_path: Path) -> None:
    database, media, backup_root = source(tmp_path)
    created = create_backup(database, media, backup_root, require_separate_volume=False)
    cloud_root = tmp_path / "cloud"
    stage_snapshot(backup_root, cloud_root)
    manifest = cloud_root / "recovery" / "manifests" / f"{created.snapshot_id}.json"
    manifest.write_text(manifest.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(BackupError, match="cloud_manifest_checksum_mismatch"):
        verify_cloud_snapshot(cloud_root, created.snapshot_id)


def test_roles_are_fail_closed(tmp_path: Path) -> None:
    primary = tmp_path / "primary.json"
    primary.write_text(json.dumps({"role": "PRIMARY", "databaseWriter": True}), encoding="utf-8")
    standby = tmp_path / "standby.json"
    standby.write_text(json.dumps({"role": "STANDBY", "databaseWriter": False}), encoding="utf-8")
    assert read_role(primary, "PRIMARY")["databaseWriter"] is True
    assert read_role(standby, "STANDBY")["databaseWriter"] is False
    with pytest.raises(BackupError, match="server_role_must_be_standby"):
        read_role(primary, "STANDBY")
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"role": "PRIMARY", "databaseWriter": False}), encoding="utf-8")
    with pytest.raises(BackupError, match="primary_database_writer_must_be_true"):
        read_role(broken, "PRIMARY")


def test_local_manifest_index_is_created_before_completion(tmp_path: Path) -> None:
    database, media, backup_root = source(tmp_path)
    created = create_backup(database, media, backup_root, require_separate_volume=False)
    indexed = backup_root / "manifests" / f"{created.snapshot_id}.json"
    assert indexed.read_bytes() == (created.snapshot_dir / "manifest.json").read_bytes()
