from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.storage.backup import (  # noqa: E402
    BackupError,
    create_backup,
    rehearse_restore,
    restore_snapshot,
    sha256_file,
    validate_backup_destination,
    verify_snapshot,
)


def create_source(tmp_path: Path) -> tuple[Path, Path]:
    database = tmp_path / "source" / "live.sqlite3"
    media = tmp_path / "source" / "media"
    media.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        connection.execute("INSERT INTO users (name) VALUES ('test-user')")
    (media / "one.webp").write_bytes(b"first-image")
    (media / "nested").mkdir()
    (media / "nested" / "two.png").write_bytes(b"second-image")
    return database, media


def test_consistent_backup_incremental_media_verify_and_restore(tmp_path: Path) -> None:
    database, media = create_source(tmp_path)
    backup_root = tmp_path / "backup"

    first = create_backup(database, media, backup_root, require_separate_volume=False)
    assert first.media_files == 2
    assert first.copied_objects == 2
    assert first.reused_objects == 0
    verified = verify_snapshot(backup_root, first.snapshot_id)
    assert verified.media_files == 2

    (media / "one.webp").write_bytes(b"first-image-updated")
    second = create_backup(database, media, backup_root, require_separate_volume=False)
    assert second.copied_objects == 1
    assert second.reused_objects == 1

    restored = tmp_path / "restored"
    restore_snapshot(backup_root, restored, second.snapshot_id)
    assert (restored / "media" / "one.webp").read_bytes() == b"first-image-updated"
    assert (restored / "media" / "nested" / "two.png").read_bytes() == b"second-image"
    with sqlite3.connect(restored / "database.sqlite3") as connection:
        assert connection.execute("SELECT name FROM users").fetchone()[0] == "test-user"


def test_manifest_has_checksums_totals_and_no_source_secret_paths(tmp_path: Path) -> None:
    database, media = create_source(tmp_path)
    backup_root = tmp_path / "backup"
    result = create_backup(database, media, backup_root, require_separate_volume=False)

    manifest = json.loads((result.snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["database"]["quick_check"] == "ok"
    assert manifest["database"]["sha256"] == sha256_file(result.snapshot_dir / "database.sqlite3")
    assert manifest["media"]["total_files"] == 2
    assert manifest["media"]["total_bytes"] == len(b"first-image") + len(b"second-image")
    document = json.dumps(manifest)
    assert str(database) not in document
    assert str(media) not in document


def test_backup_api_includes_committed_wal_rows_while_writer_is_open(tmp_path: Path) -> None:
    database, media = create_source(tmp_path)
    writer = sqlite3.connect(database)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("INSERT INTO users (name) VALUES ('wal-user')")
        writer.commit()

        result = create_backup(database, media, tmp_path / "backup", require_separate_volume=False)

        with sqlite3.connect(result.snapshot_dir / "database.sqlite3") as restored:
            assert restored.execute("SELECT name FROM users ORDER BY id").fetchall() == [
                ("test-user",),
                ("wal-user",),
            ]
    finally:
        writer.close()


def test_corrupt_media_object_is_detected(tmp_path: Path) -> None:
    database, media = create_source(tmp_path)
    backup_root = tmp_path / "backup"
    result = create_backup(database, media, backup_root, require_separate_volume=False)
    manifest = json.loads((result.snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
    checksum = manifest["media"]["files"][0]["sha256"]
    (backup_root / "media-objects" / checksum[:2] / checksum).write_bytes(b"corrupt")

    with pytest.raises(BackupError, match="backup_media_object_missing_or_wrong_size"):
        verify_snapshot(backup_root, result.snapshot_id)


def test_tampered_manifest_path_is_rejected_before_restore(tmp_path: Path) -> None:
    database, media = create_source(tmp_path)
    backup_root = tmp_path / "backup"
    result = create_backup(database, media, backup_root, require_separate_volume=False)
    manifest_path = result.snapshot_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["media"]["files"][0]["path"] = "..\\outside.txt"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (result.snapshot_dir / "COMPLETED").write_text(sha256_file(manifest_path) + "\n", encoding="ascii")

    with pytest.raises(BackupError, match="unsafe_manifest_media_path"):
        verify_snapshot(backup_root, result.snapshot_id)


def test_tampered_manifest_checksum_is_detected(tmp_path: Path) -> None:
    database, media = create_source(tmp_path)
    backup_root = tmp_path / "backup"
    result = create_backup(database, media, backup_root, require_separate_volume=False)
    manifest_path = result.snapshot_dir / "manifest.json"
    manifest_path.write_text(manifest_path.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(BackupError, match="manifest_checksum_mismatch"):
        verify_snapshot(backup_root, result.snapshot_id)


def test_tampered_database_manifest_path_is_rejected(tmp_path: Path) -> None:
    database, media = create_source(tmp_path)
    backup_root = tmp_path / "backup"
    result = create_backup(database, media, backup_root, require_separate_volume=False)
    manifest_path = result.snapshot_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["database"]["file"] = "../live.sqlite3"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (result.snapshot_dir / "COMPLETED").write_text(sha256_file(manifest_path) + "\n", encoding="ascii")

    with pytest.raises(BackupError, match="manifest_database_path_invalid"):
        verify_snapshot(backup_root, result.snapshot_id)


def test_restore_refuses_nonempty_destination(tmp_path: Path) -> None:
    database, media = create_source(tmp_path)
    backup_root = tmp_path / "backup"
    result = create_backup(database, media, backup_root, require_separate_volume=False)
    destination = tmp_path / "existing"
    destination.mkdir()
    (destination / "do-not-touch.txt").write_text("preserve", encoding="utf-8")

    with pytest.raises(BackupError, match="restore_destination_not_empty"):
        restore_snapshot(backup_root, destination, result.snapshot_id)
    assert (destination / "do-not-touch.txt").read_text(encoding="utf-8") == "preserve"


def test_restore_refuses_destination_inside_backup_root(tmp_path: Path) -> None:
    database, media = create_source(tmp_path)
    backup_root = tmp_path / "backup"
    result = create_backup(database, media, backup_root, require_separate_volume=False)

    with pytest.raises(BackupError, match="restore_destination_inside_backup_root"):
        restore_snapshot(backup_root, backup_root / "restore", result.snapshot_id)


def test_restore_rehearsal_cleans_temporary_copy(tmp_path: Path) -> None:
    database, media = create_source(tmp_path)
    backup_root = tmp_path / "backup"
    result = create_backup(database, media, backup_root, require_separate_volume=False)
    work_root = tmp_path / "rehearsals"

    verified = rehearse_restore(backup_root, result.snapshot_id, work_root)

    assert verified.snapshot_id == result.snapshot_id
    assert list(work_root.iterdir()) == []


def test_destination_same_volume_is_rejected_by_production_default(tmp_path: Path) -> None:
    database, media = create_source(tmp_path)
    with pytest.raises(BackupError, match="backup_root_must_use_separate_volume"):
        validate_backup_destination(tmp_path / "same-drive", database, media)


def test_media_symlink_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, media = create_source(tmp_path)
    link = media / "linked.webp"
    link.write_bytes(b"simulated-link")
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda self: self == link or original_is_symlink(self),
    )
    with pytest.raises(BackupError, match="media_symlink_not_allowed"):
        create_backup(database, media, tmp_path / "backup", require_separate_volume=False)


def test_tools_never_offer_in_place_production_restore() -> None:
    backup_source = (ROOT / "tools" / "backup_production.py").read_text(encoding="utf-8")
    restore_source = (ROOT / "tools" / "restore_backup.py").read_text(encoding="utf-8")
    module_source = (BACKEND / "app" / "storage" / "backup.py").read_text(encoding="utf-8")

    assert ".backup(" in module_source
    assert "shutil.copy2(source" not in module_source
    assert "--destination" in restore_source
    assert "DATABASE_URL" not in restore_source
    assert "--create-config" in backup_source
