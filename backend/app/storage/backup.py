"""Consistent SQLite and incremental media backup primitives.

The module is deliberately independent from the FastAPI application.  It reads
the live database and media tree, but never mutates either source.
"""

from __future__ import annotations

import hashlib
import json
import os
import string
import shutil
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


MANIFEST_VERSION = 1
COMPLETE_MARKER = "COMPLETED"
RESTORE_COMPLETE_MARKER = "RESTORE_COMPLETED"


class BackupError(RuntimeError):
    """A backup or restore safety invariant was not satisfied."""


@dataclass(frozen=True)
class BackupResult:
    snapshot_id: str
    snapshot_dir: Path
    database_bytes: int
    media_files: int
    media_bytes: int
    copied_objects: int
    reused_objects: int


@dataclass(frozen=True)
class VerificationResult:
    snapshot_id: str
    database_bytes: int
    media_files: int
    media_bytes: int


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def sqlite_quick_check(path: Path) -> str:
    uri = path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=30)) as connection:
        rows = connection.execute("PRAGMA quick_check").fetchall()
    result = "\n".join(str(row[0]) for row in rows)
    if result != "ok":
        raise BackupError("database_quick_check_failed")
    return result


def _same_storage_volume(first: Path, second: Path) -> bool:
    first_resolved = first.expanduser().resolve()
    second_resolved = second.expanduser().resolve()
    if os.name == "nt":
        return first_resolved.drive.casefold() == second_resolved.drive.casefold()

    def existing_parent(path: Path) -> Path:
        candidate = path
        while not candidate.exists() and candidate != candidate.parent:
            candidate = candidate.parent
        return candidate

    return existing_parent(first_resolved).stat().st_dev == existing_parent(second_resolved).stat().st_dev


def validate_backup_destination(
    backup_root: Path,
    database: Path,
    media_root: Path,
    *,
    require_separate_volume: bool = True,
) -> Path:
    root = backup_root.expanduser().resolve()
    database = database.expanduser().resolve()
    media_root = media_root.expanduser().resolve()
    if not database.is_file():
        raise BackupError("database_not_found")
    if not media_root.is_dir():
        raise BackupError("media_root_not_found")
    try:
        root.relative_to(media_root)
    except ValueError:
        pass
    else:
        raise BackupError("backup_root_inside_media_root")
    if require_separate_volume and (
        _same_storage_volume(root, database) or _same_storage_volume(root, media_root)
    ):
        raise BackupError("backup_root_must_use_separate_volume")
    anchor = Path(root.anchor)
    if root.anchor and not anchor.exists():
        raise BackupError("backup_volume_not_available")
    return root


def _snapshot_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def _atomic_json(path: Path, document: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _backup_database(source: Path, destination: Path) -> dict[str, Any]:
    source_uri = source.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True, timeout=30)) as source_connection:
        source_connection.execute("PRAGMA query_only = ON")
        with closing(sqlite3.connect(destination)) as destination_connection:
            source_connection.backup(destination_connection, pages=1024, sleep=0.05)
            destination_connection.commit()
    quick_check = sqlite_quick_check(destination)
    return {
        "file": destination.name,
        "size": destination.stat().st_size,
        "sha256": sha256_file(destination),
        "quick_check": quick_check,
    }


def _relative_media_files(media_root: Path) -> list[tuple[str, Path]]:
    entries: list[tuple[str, Path]] = []
    for directory, directory_names, file_names in os.walk(media_root, followlinks=False):
        directory_path = Path(directory)
        for name in list(directory_names):
            if (directory_path / name).is_symlink():
                raise BackupError("media_symlink_not_allowed")
        for name in file_names:
            path = directory_path / name
            if path.is_symlink() or not path.is_file():
                raise BackupError("media_symlink_not_allowed")
            relative = path.relative_to(media_root).as_posix()
            entries.append((relative, path))
    entries.sort(key=lambda item: item[0])
    return entries


def media_source_totals(media_root: Path) -> tuple[int, int]:
    entries = _relative_media_files(media_root.expanduser().resolve())
    return len(entries), sum(path.stat().st_size for _relative, path in entries)


def _copy_stable_media_object(
    source: Path,
    object_store: Path,
    verified_objects: set[str],
    attempts: int = 3,
) -> tuple[str, int, bool]:
    object_store.mkdir(parents=True, exist_ok=True)
    for _attempt in range(attempts):
        before = source.stat()
        checksum = sha256_file(source)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            continue
        object_path = object_store / checksum[:2] / checksum
        object_path.parent.mkdir(parents=True, exist_ok=True)
        if object_path.exists():
            if object_path.stat().st_size != after.st_size or (
                checksum not in verified_objects and sha256_file(object_path) != checksum
            ):
                raise BackupError("existing_media_object_corrupt")
            verified_objects.add(checksum)
            return checksum, after.st_size, False
        digest = hashlib.sha256()
        with tempfile.NamedTemporaryFile(prefix=".media-", suffix=".tmp", dir=object_store, delete=False) as output:
            temporary = Path(output.name)
            try:
                with source.open("rb") as input_stream:
                    while chunk := input_stream.read(1024 * 1024):
                        digest.update(chunk)
                        output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        copied_after = source.stat()
        if (
            (after.st_size, after.st_mtime_ns) != (copied_after.st_size, copied_after.st_mtime_ns)
            or digest.hexdigest() != checksum
        ):
            temporary.unlink(missing_ok=True)
            continue
        os.replace(temporary, object_path)
        verified_objects.add(checksum)
        return checksum, after.st_size, True
    raise BackupError("media_file_changed_during_backup")


def create_backup(
    database: Path,
    media_root: Path,
    backup_root: Path,
    *,
    require_separate_volume: bool = True,
) -> BackupResult:
    database = database.expanduser().resolve()
    media_root = media_root.expanduser().resolve()
    root = validate_backup_destination(
        backup_root,
        database,
        media_root,
        require_separate_volume=require_separate_volume,
    )
    root.mkdir(parents=True, exist_ok=True)
    snapshots = root / "snapshots"
    manifests = root / "manifests"
    object_store = root / "media-objects"
    snapshots.mkdir(exist_ok=True)
    manifests.mkdir(exist_ok=True)
    snapshot_id = _snapshot_id()
    completed = snapshots / snapshot_id
    completed.mkdir()

    database_metadata = _backup_database(database, completed / "database.sqlite3")
    media_entries: list[dict[str, Any]] = []
    copied_objects = 0
    reused_objects = 0
    media_bytes = 0
    verified_objects: set[str] = set()
    for relative, source in _relative_media_files(media_root):
        checksum, size, copied = _copy_stable_media_object(source, object_store, verified_objects)
        copied_objects += int(copied)
        reused_objects += int(not copied)
        media_bytes += size
        media_entries.append({"path": relative, "size": size, "sha256": checksum})

    manifest = {
        "version": MANIFEST_VERSION,
        "snapshot_id": snapshot_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "database": database_metadata,
        "media": {
            "files": media_entries,
            "total_files": len(media_entries),
            "total_bytes": media_bytes,
            "copied_objects": copied_objects,
            "reused_objects": reused_objects,
        },
    }
    manifest_path = completed / "manifest.json"
    _atomic_json(manifest_path, manifest)
    manifest_index = manifests / f"{snapshot_id}.json"
    _atomic_json(manifest_index, manifest)
    if sha256_file(manifest_index) != sha256_file(manifest_path):
        raise BackupError("manifest_index_checksum_mismatch")
    # This marker is the commit point. A crash can leave an unmarked directory,
    # but readers will never treat it as a completed snapshot.
    (completed / COMPLETE_MARKER).write_text(sha256_file(manifest_path) + "\n", encoding="ascii")
    return BackupResult(
        snapshot_id=snapshot_id,
        snapshot_dir=completed,
        database_bytes=int(database_metadata["size"]),
        media_files=len(media_entries),
        media_bytes=media_bytes,
        copied_objects=copied_objects,
        reused_objects=reused_objects,
    )


def _safe_relative_path(value: str) -> Path:
    if "\\" in value or ":" in value or "\x00" in value:
        raise BackupError("unsafe_manifest_media_path")
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise BackupError("unsafe_manifest_media_path")
    return Path(*pure.parts)


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in string.hexdigits for character in value)
        and value == value.lower()
    )


def completed_snapshots(backup_root: Path) -> list[Path]:
    snapshots = backup_root.expanduser().resolve() / "snapshots"
    if not snapshots.is_dir():
        return []
    return sorted(
        path
        for path in snapshots.iterdir()
        if path.is_dir() and not path.is_symlink() and (path / COMPLETE_MARKER).is_file()
    )


def resolve_snapshot(backup_root: Path, snapshot: str = "latest") -> Path:
    available = completed_snapshots(backup_root)
    if not available:
        raise BackupError("no_completed_snapshots")
    if snapshot == "latest":
        return available[-1]
    candidate = backup_root.expanduser().resolve() / "snapshots" / snapshot
    if candidate not in available:
        raise BackupError("snapshot_not_found_or_incomplete")
    return candidate


def load_manifest(snapshot_dir: Path) -> dict[str, Any]:
    marker_path = snapshot_dir / COMPLETE_MARKER
    manifest_path = snapshot_dir / "manifest.json"
    if not marker_path.is_file():
        raise BackupError("snapshot_incomplete")
    try:
        expected_manifest_checksum = marker_path.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise BackupError("snapshot_marker_unreadable") from exc
    legacy_marker = expected_manifest_checksum == "ok"
    if (not legacy_marker and not _valid_sha256(expected_manifest_checksum)) or not manifest_path.is_file():
        raise BackupError("snapshot_marker_invalid")
    if not legacy_marker and sha256_file(manifest_path) != expected_manifest_checksum:
        raise BackupError("manifest_checksum_mismatch")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupError("manifest_unreadable") from exc
    if manifest.get("version") != MANIFEST_VERSION or manifest.get("snapshot_id") != snapshot_dir.name:
        raise BackupError("manifest_identity_invalid")
    return manifest


def verify_snapshot(backup_root: Path, snapshot: str = "latest") -> VerificationResult:
    root = backup_root.expanduser().resolve()
    snapshot_dir = resolve_snapshot(root, snapshot)
    manifest = load_manifest(snapshot_dir)
    database_metadata = manifest.get("database", {})
    if database_metadata.get("file") != "database.sqlite3":
        raise BackupError("manifest_database_path_invalid")
    database_path = snapshot_dir / "database.sqlite3"
    if not database_path.is_file():
        raise BackupError("backup_database_missing")
    if database_path.stat().st_size != database_metadata.get("size"):
        raise BackupError("backup_database_size_mismatch")
    if sha256_file(database_path) != database_metadata.get("sha256"):
        raise BackupError("backup_database_checksum_mismatch")
    sqlite_quick_check(database_path)

    media = manifest.get("media", {})
    entries = media.get("files")
    if not isinstance(entries, list):
        raise BackupError("manifest_media_invalid")
    seen: set[str] = set()
    total_bytes = 0
    for entry in entries:
        relative = str(entry.get("path", ""))
        _safe_relative_path(relative)
        if relative in seen:
            raise BackupError("manifest_media_path_duplicate")
        seen.add(relative)
        checksum = str(entry.get("sha256", ""))
        size = entry.get("size")
        if not _valid_sha256(checksum) or not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise BackupError("manifest_media_entry_invalid")
        object_path = root / "media-objects" / checksum[:2] / checksum
        if not object_path.is_file() or object_path.stat().st_size != size:
            raise BackupError("backup_media_object_missing_or_wrong_size")
        if sha256_file(object_path) != checksum:
            raise BackupError("backup_media_checksum_mismatch")
        total_bytes += size
    if len(entries) != media.get("total_files") or total_bytes != media.get("total_bytes"):
        raise BackupError("manifest_media_totals_mismatch")
    return VerificationResult(
        snapshot_id=snapshot_dir.name,
        database_bytes=database_path.stat().st_size,
        media_files=len(entries),
        media_bytes=total_bytes,
    )


def restore_snapshot(backup_root: Path, destination: Path, snapshot: str = "latest") -> VerificationResult:
    root = backup_root.expanduser().resolve()
    verified = verify_snapshot(root, snapshot)
    snapshot_dir = resolve_snapshot(root, snapshot)
    manifest = load_manifest(snapshot_dir)
    destination = destination.expanduser().resolve()
    try:
        destination.relative_to(root)
    except ValueError:
        pass
    else:
        raise BackupError("restore_destination_inside_backup_root")
    if destination.exists() and any(destination.iterdir()):
        raise BackupError("restore_destination_not_empty")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(exist_ok=True)
    restored_database = destination / "database.sqlite3"
    shutil.copy2(snapshot_dir / manifest["database"]["file"], restored_database)
    media_destination = destination / "media"
    media_destination.mkdir()
    for entry in manifest["media"]["files"]:
        relative = _safe_relative_path(entry["path"])
        target = (media_destination / relative).resolve()
        try:
            target.relative_to(media_destination.resolve())
        except ValueError as exc:
            raise BackupError("unsafe_manifest_media_path") from exc
        target.parent.mkdir(parents=True, exist_ok=True)
        checksum = entry["sha256"]
        shutil.copy2(root / "media-objects" / checksum[:2] / checksum, target)
        if target.stat().st_size != entry["size"] or sha256_file(target) != checksum:
            raise BackupError("restored_media_checksum_mismatch")
    if sha256_file(restored_database) != manifest["database"]["sha256"]:
        raise BackupError("restored_database_checksum_mismatch")
    sqlite_quick_check(restored_database)
    (destination / RESTORE_COMPLETE_MARKER).write_text("ok\n", encoding="ascii")
    return verified


def rehearse_restore(backup_root: Path, snapshot: str = "latest", work_root: Path | None = None) -> VerificationResult:
    temporary_parent = None if work_root is None else work_root.expanduser().resolve()
    if temporary_parent is not None:
        temporary_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="izo-restore-rehearsal-", dir=temporary_parent) as temporary:
        destination = Path(temporary) / "restored"
        result = restore_snapshot(backup_root, destination, snapshot)
        if not (destination / "database.sqlite3").is_file() or not (destination / "media").is_dir():
            raise BackupError("restore_rehearsal_postcondition_failed")
        return result
