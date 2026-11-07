from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.storage import backup  # noqa: E402
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


def tree_checksums(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.fixture
def snapshot_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, backup.BackupResult, tuple[Path, Path]]:
    snapshot_ids = iter(("20260101T000000.000000Z", "20260102T000000.000000Z"))
    monkeypatch.setattr(backup, "_snapshot_id", lambda: next(snapshot_ids))
    sources = []
    for label, payload in (("A", b"media-from-A"), ("B", b"media-from-B-is-newer")):
        database, media = create_source(tmp_path / "sources" / label)
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("UPDATE users SET name = ?", (f"snapshot-{label}",))
            connection.commit()
        (media / "one.webp").write_bytes(payload)
        sources.append((database, media))
    backup_root = tmp_path / "backup"
    first = create_backup(*sources[0], backup_root, require_separate_volume=False)
    return backup_root, first, sources[1]


@pytest.mark.parametrize("selector", ("latest", "explicit"))
@pytest.mark.parametrize("publish_newer", (False, True), ids=("steady", "competing"))
@pytest.mark.parametrize("legacy_marker", (False, True), ids=("checksummed", "legacy"))
@pytest.mark.parametrize("rehearsal", (False, True), ids=("direct", "rehearsal"))
def test_restore_stays_bound_to_verified_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot_sources,
    selector: str, publish_newer: bool, legacy_marker: bool, rehearsal: bool,
) -> None:
    backup_root, first, newer_source = snapshot_sources
    if legacy_marker:
        (first.snapshot_dir / backup.COMPLETE_MARKER).write_text("ok\n", encoding="ascii")
    sources_before = tree_checksums(tmp_path / "sources")
    backup_initial = tree_checksums(backup_root)
    backup_before: dict[str, str] = {}
    verifications = []
    original_verify = backup.verify_snapshot

    def verify_then_publish(root: Path, snapshot: str = "latest"):
        verified = original_verify(root, snapshot)
        verifications.append(verified)
        if len(verifications) == 1:
            if publish_newer:
                create_backup(*newer_source, backup_root, require_separate_volume=False)
            backup_before.update(tree_checksums(backup_root))
        return verified

    monkeypatch.setattr(backup, "verify_snapshot", verify_then_publish)
    observations = []
    restored_hashes = []
    destinations = []
    original_restore = backup.restore_snapshot

    def observe_restore(root: Path, destination: Path, snapshot: str = "latest"):
        result = original_restore(root, destination, snapshot)
        destinations.append(destination)
        with closing(sqlite3.connect(destination / "database.sqlite3")) as connection:
            rows = connection.execute("SELECT name FROM users ORDER BY id").fetchall()
        media_bytes = (destination / "media" / "one.webp").read_bytes()
        observations.append((result.snapshot_id, rows, media_bytes))
        restored_hashes.append((
            sha256_file(destination / "database.sqlite3"), tree_checksums(destination / "media"),
        ))
        assert (destination / backup.RESTORE_COMPLETE_MARKER).read_text(encoding="ascii") == "ok\n"
        return result

    monkeypatch.setattr(backup, "restore_snapshot", observe_restore)
    work_root = tmp_path / "rehearsals"
    foreign = work_root / "izo-restore-rehearsal-foreign"
    foreign.mkdir(parents=True)
    (foreign / "keep.txt").write_text("foreign rehearsal", encoding="utf-8")
    (work_root / "keep.txt").write_text("unrelated file", encoding="utf-8")
    work_before = tree_checksums(work_root)
    requested = first.snapshot_id if selector == "explicit" else "latest"
    if rehearsal:
        result = backup.rehearse_restore(backup_root, requested, work_root)
    else:
        result = backup.restore_snapshot(backup_root, tmp_path / "restored", requested)

    expected = (first.snapshot_id, [("snapshot-A",)], b"media-from-A")
    assert observations == [expected], f"verified/restored observations: {observations!r}"
    assert result == verifications[0]
    assert all(item.snapshot_id == first.snapshot_id for item in verifications)
    assert result.media_bytes == len(b"media-from-A") + len(b"second-image")
    manifest = json.loads((first.snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
    assert restored_hashes == [(
        manifest["database"]["sha256"],
        {entry["path"]: entry["sha256"] for entry in manifest["media"]["files"]},
    )]
    if rehearsal:
        assert not destinations[0].parent.exists()
    assert tree_checksums(tmp_path / "sources") == sources_before
    assert tree_checksums(backup_root) == backup_before
    assert {path: backup_before[path] for path in backup_initial} == backup_initial
    assert tree_checksums(work_root) == work_before
    assert sorted(path.name for path in work_root.iterdir()) == [foreign.name, "keep.txt"]
    if publish_newer:
        assert original_verify(backup_root).snapshot_id != first.snapshot_id


@pytest.mark.parametrize("rehearsal", (False, True), ids=("direct", "rehearsal"))
@pytest.mark.parametrize(("damage", "error"), (
    ("missing", "snapshot_not_found_or_incomplete"),
    ("incomplete", "snapshot_not_found_or_incomplete"),
    ("marker", "snapshot_marker_invalid"),
    ("manifest", "manifest_checksum_mismatch"),
    ("database", "restored_database_checksum_mismatch"),
    ("media", "restored_media_checksum_mismatch"),
    ("symlink", "snapshot_not_found_or_incomplete"),
    ("media-path", "unsafe_manifest_media_path"),
))
def test_restore_rejects_unusable_selected_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot_sources,
    rehearsal: bool, damage: str, error: str,
) -> None:
    backup_root, first, newer_source = snapshot_sources
    sources_before = tree_checksums(tmp_path / "sources")
    backup_before: dict[str, str] = {}
    original_verify = backup.verify_snapshot
    original_is_symlink = Path.is_symlink
    published = []

    def verify_then_damage(root: Path, snapshot: str = "latest"):
        verified = original_verify(root, snapshot)
        assert verified.snapshot_id == first.snapshot_id
        if published:
            return verified
        published.append(create_backup(*newer_source, backup_root, require_separate_volume=False))
        marker = first.snapshot_dir / backup.COMPLETE_MARKER
        manifest_path = first.snapshot_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if damage == "missing":
            first.snapshot_dir.rename(tmp_path / "removed-A")
        elif damage == "incomplete":
            marker.unlink()
        elif damage == "marker":
            marker.write_text("invalid\n", encoding="ascii")
        elif damage == "manifest":
            manifest_path.write_bytes(manifest_path.read_bytes() + b" ")
        elif damage in {"database", "media"}:
            target = first.snapshot_dir / "database.sqlite3"
            if damage == "media":
                entry = next(item for item in manifest["media"]["files"] if item["path"] == "one.webp")
                checksum = entry["sha256"]
                target = backup_root / "media-objects" / checksum[:2] / checksum
            contents = target.read_bytes()
            target.write_bytes(bytes((contents[0] ^ 1,)) + contents[1:])
        elif damage == "symlink":
            monkeypatch.setattr(Path, "is_symlink", lambda path: (
                path == first.snapshot_dir or original_is_symlink(path)
            ))
        elif damage == "media-path":
            manifest["media"]["files"][0]["path"] = "../outside.txt"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            marker.write_text(sha256_file(manifest_path) + "\n", encoding="ascii")
        backup_before.update(tree_checksums(backup_root))
        return verified

    monkeypatch.setattr(backup, "verify_snapshot", verify_then_damage)
    original_restore = backup.restore_snapshot
    destinations = []
    completion_markers = []

    def observe_restore(root: Path, destination: Path, snapshot: str = "latest"):
        destinations.append(destination)
        try:
            return original_restore(root, destination, snapshot)
        finally:
            completion_markers.append((destination / backup.RESTORE_COMPLETE_MARKER).exists())

    monkeypatch.setattr(backup, "restore_snapshot", observe_restore)
    work_root = tmp_path / "rehearsals"
    foreign = work_root / "izo-restore-rehearsal-foreign"
    foreign.mkdir(parents=True)
    (foreign / "keep.txt").write_text("foreign rehearsal", encoding="utf-8")
    (work_root / "keep.txt").write_text("unrelated file", encoding="utf-8")
    work_before = tree_checksums(work_root)
    with pytest.raises(BackupError, match=error):
        if rehearsal:
            backup.rehearse_restore(backup_root, work_root=work_root)
        else:
            backup.restore_snapshot(backup_root, tmp_path / "restored")

    assert completion_markers == [False]
    assert not (destinations[0] / "outside.txt").exists()
    if rehearsal:
        assert not destinations[0].parent.exists()
    assert len(published) == 1
    assert original_verify(backup_root).snapshot_id == published[0].snapshot_id
    assert tree_checksums(tmp_path / "sources") == sources_before
    assert tree_checksums(backup_root) == backup_before
    assert tree_checksums(work_root) == work_before
    assert sorted(path.name for path in work_root.iterdir()) == [foreign.name, "keep.txt"]
