"""Stage verified IZO ASA backups to cloud transport or a standby cache."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.storage.backup import (  # noqa: E402
    COMPLETE_MARKER,
    BackupError,
    VerificationResult,
    load_manifest,
    rehearse_restore,
    resolve_snapshot,
    sha256_file,
    sqlite_quick_check,
    verify_snapshot,
)
from backup_production import read_config  # noqa: E402


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def read_role(path: Path, expected: str) -> dict[str, Any]:
    try:
        document = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupError("server_role_unreadable") from exc
    role = str(document.get("role", "")).upper()
    writer = document.get("databaseWriter")
    if role != expected:
        raise BackupError(f"server_role_must_be_{expected.lower()}")
    if expected == "PRIMARY" and writer is not True:
        raise BackupError("primary_database_writer_must_be_true")
    if expected == "STANDBY" and writer is not False:
        raise BackupError("standby_database_writer_must_be_false")
    return document


def _valid_checksum(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _cloud_paths(cloud_root: Path, snapshot_id: str) -> tuple[Path, Path, Path]:
    root = cloud_root.expanduser().resolve()
    return (
        root / "database" / "snapshots" / snapshot_id,
        root / "recovery" / "manifests" / f"{snapshot_id}.json",
        root / "data" / "media-objects",
    )


def _copy_verified(source: Path, destination: Path, checksum: str, size: int) -> None:
    if destination.is_file():
        if destination.stat().st_size != size or sha256_file(destination) != checksum:
            raise BackupError("cloud_existing_file_corrupt")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=".incoming-", dir=destination.parent, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        shutil.copy2(source, temporary)
        if temporary.stat().st_size != size or sha256_file(temporary) != checksum:
            raise BackupError("cloud_copy_checksum_mismatch")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def verify_cloud_snapshot(cloud_root: Path, snapshot_id: str) -> VerificationResult:
    snapshot_dir, manifest_path, object_store = _cloud_paths(cloud_root, snapshot_id)
    marker = snapshot_dir / COMPLETE_MARKER
    if not marker.is_file() or not manifest_path.is_file():
        raise BackupError("cloud_snapshot_incomplete")
    expected_manifest_sha = marker.read_text(encoding="ascii").strip()
    if not _valid_checksum(expected_manifest_sha) or sha256_file(manifest_path) != expected_manifest_sha:
        raise BackupError("cloud_manifest_checksum_mismatch")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupError("cloud_manifest_unreadable") from exc
    if manifest.get("version") != 1 or manifest.get("snapshot_id") != snapshot_id:
        raise BackupError("cloud_manifest_identity_invalid")
    database = snapshot_dir / "database.sqlite3"
    metadata = manifest.get("database", {})
    if metadata.get("file") != "database.sqlite3" or not database.is_file():
        raise BackupError("cloud_database_missing")
    if database.stat().st_size != metadata.get("size") or sha256_file(database) != metadata.get("sha256"):
        raise BackupError("cloud_database_checksum_mismatch")
    sqlite_quick_check(database)
    entries = manifest.get("media", {}).get("files")
    if not isinstance(entries, list):
        raise BackupError("cloud_manifest_media_invalid")
    total_bytes = 0
    for entry in entries:
        checksum = entry.get("sha256")
        size = entry.get("size")
        if not _valid_checksum(checksum) or not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise BackupError("cloud_manifest_media_entry_invalid")
        media_object = object_store / checksum[:2] / checksum
        if not media_object.is_file() or media_object.stat().st_size != size:
            raise BackupError("cloud_media_object_missing_or_wrong_size")
        if sha256_file(media_object) != checksum:
            raise BackupError("cloud_media_checksum_mismatch")
        total_bytes += size
    media = manifest["media"]
    if len(entries) != media.get("total_files") or total_bytes != media.get("total_bytes"):
        raise BackupError("cloud_manifest_media_totals_mismatch")
    return VerificationResult(snapshot_id, database.stat().st_size, len(entries), total_bytes)


def stage_snapshot(local_root: Path, cloud_root: Path, snapshot: str = "latest") -> VerificationResult:
    verified = verify_snapshot(local_root, snapshot)
    source_snapshot = resolve_snapshot(local_root, verified.snapshot_id)
    manifest = load_manifest(source_snapshot)
    snapshot_dir, manifest_path, cloud_objects = _cloud_paths(cloud_root, verified.snapshot_id)
    marker = snapshot_dir / COMPLETE_MARKER
    if marker.is_file():
        return verify_cloud_snapshot(cloud_root, verified.snapshot_id)

    snapshot_dir.mkdir(parents=True, exist_ok=True)
    database_meta = manifest["database"]
    _copy_verified(
        source_snapshot / "database.sqlite3",
        snapshot_dir / "database.sqlite3",
        database_meta["sha256"],
        database_meta["size"],
    )
    for entry in manifest["media"]["files"]:
        checksum = entry["sha256"]
        _copy_verified(
            local_root / "media-objects" / checksum[:2] / checksum,
            cloud_objects / checksum[:2] / checksum,
            checksum,
            entry["size"],
        )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_manifest = manifest_path.with_name(manifest_path.name + ".tmp")
    shutil.copy2(source_snapshot / "manifest.json", temporary_manifest)
    manifest_sha = sha256_file(source_snapshot / "manifest.json")
    if sha256_file(temporary_manifest) != manifest_sha:
        temporary_manifest.unlink(missing_ok=True)
        raise BackupError("cloud_manifest_copy_checksum_mismatch")
    os.replace(temporary_manifest, manifest_path)

    # Verify every staged payload before publishing the commit marker.
    if sha256_file(snapshot_dir / "database.sqlite3") != database_meta["sha256"]:
        raise BackupError("cloud_database_checksum_mismatch")
    sqlite_quick_check(snapshot_dir / "database.sqlite3")
    marker.write_text(manifest_sha + "\n", encoding="ascii")
    return verify_cloud_snapshot(cloud_root, verified.snapshot_id)


def receive_snapshot(cloud_root: Path, cache_root: Path, snapshot_id: str) -> VerificationResult:
    cloud_verified = verify_cloud_snapshot(cloud_root, snapshot_id)
    cloud_snapshot, cloud_manifest, cloud_objects = _cloud_paths(cloud_root, snapshot_id)
    cache_root = cache_root.expanduser().resolve()
    cache_snapshot = cache_root / "snapshots" / snapshot_id
    cache_manifest = cache_snapshot / "manifest.json"
    cache_snapshot.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(cloud_manifest.read_text(encoding="utf-8"))
    database_meta = manifest["database"]
    _copy_verified(
        cloud_snapshot / "database.sqlite3",
        cache_snapshot / "database.sqlite3",
        database_meta["sha256"],
        database_meta["size"],
    )
    for entry in manifest["media"]["files"]:
        checksum = entry["sha256"]
        _copy_verified(
            cloud_objects / checksum[:2] / checksum,
            cache_root / "media-objects" / checksum[:2] / checksum,
            checksum,
            entry["size"],
        )
    shutil.copy2(cloud_manifest, cache_manifest)
    marker_sha = sha256_file(cache_manifest)
    (cache_snapshot / COMPLETE_MARKER).write_text(marker_sha + "\n", encoding="ascii")
    local_verified = verify_snapshot(cache_root, snapshot_id)
    if local_verified != cloud_verified:
        raise BackupError("replica_verification_result_mismatch")
    return local_verified


def latest_cloud_snapshot_id(cloud_root: Path) -> str:
    snapshots = cloud_root.expanduser().resolve() / "database" / "snapshots"
    if not snapshots.is_dir():
        raise BackupError("cloud_snapshot_root_unavailable")
    available = sorted(
        path.name
        for path in snapshots.iterdir()
        if path.is_dir() and not path.is_symlink() and (path / COMPLETE_MARKER).is_file()
    )
    if not available:
        raise BackupError("no_completed_cloud_snapshots")
    return available[-1]


def update_health(path: Path, **changes: Any) -> None:
    defaults: dict[str, Any] = {
        "LastLocalBackup": None,
        "LastVerifiedBackup": None,
        "LastCloudStage": None,
        "LastReplicaReceive": None,
        "LatestSnapshotId": None,
        "DatabaseBytes": None,
        "MediaFiles": None,
        "ManifestSha256": None,
        "YandexDiskRunning": False,
        "LegacyYandexDiskRunning": False,
        "YandexSyncErrors": [],
        "CloudFolderAvailable": False,
        "YandexRouteInterface": None,
        "YandexHttpsReachable": False,
        "LocalFreeGB": None,
        "CloudStatus": "UNKNOWN",
        "OverallStatus": "ATTENTION",
        "LastError": None,
        "UpdatedAt": None,
    }
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                defaults.update(existing)
        except (OSError, ValueError):
            pass
    defaults.update(changes)
    defaults["UpdatedAt"] = _utc_now()
    _atomic_json(path, defaults)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role-config", type=Path, required=True)
    parser.add_argument("--health", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)

    local_status = subparsers.add_parser("local-status")
    local_status.add_argument("--config", type=Path, required=True)
    local_status.add_argument("--snapshot", default="latest")

    stage = subparsers.add_parser("stage")
    stage.add_argument("--config", type=Path, required=True)
    stage.add_argument("--cloud-root", type=Path, required=True)
    stage.add_argument("--snapshot", default="latest")

    receive = subparsers.add_parser("receive")
    receive.add_argument("--cloud-root", type=Path, required=True)
    receive.add_argument("--cache-root", type=Path, required=True)
    receive.add_argument("--snapshot", default="latest")
    receive.add_argument("--rehearse", action="store_true")
    receive.add_argument("--work-root", type=Path)

    args = parser.parse_args()
    try:
        if args.command == "local-status":
            read_role(args.role_config, "PRIMARY")
            local_root = read_config(args.config).expanduser().resolve()
            result = verify_snapshot(local_root, args.snapshot)
            snapshot_dir = resolve_snapshot(local_root, result.snapshot_id)
            print(
                f"BACKUP_VERIFY_OK snapshot={result.snapshot_id} databaseBytes={result.database_bytes} "
                f"mediaFiles={result.media_files} mediaBytes={result.media_bytes}"
            )
            update_health(
                args.health,
                LastLocalBackup=_utc_now(),
                LastVerifiedBackup=_utc_now(),
                LatestSnapshotId=result.snapshot_id,
                DatabaseBytes=result.database_bytes,
                MediaFiles=result.media_files,
                ManifestSha256=sha256_file(snapshot_dir / "manifest.json"),
                LocalFreeGB=round(shutil.disk_usage(local_root).free / (1024**3), 2),
                OverallStatus="OK",
                LastError=None,
            )
            print(f"LOCAL_BACKUP_STATUS_OK snapshot={result.snapshot_id}")
        elif args.command == "stage":
            read_role(args.role_config, "PRIMARY")
            local_root = read_config(args.config).expanduser().resolve()
            result = stage_snapshot(local_root, args.cloud_root, args.snapshot)
            manifest = args.cloud_root / "recovery" / "manifests" / f"{result.snapshot_id}.json"
            update_health(
                args.health,
                LastCloudStage=_utc_now(),
                LatestSnapshotId=result.snapshot_id,
                DatabaseBytes=result.database_bytes,
                MediaFiles=result.media_files,
                ManifestSha256=sha256_file(manifest),
                CloudFolderAvailable=True,
                CloudStatus="STAGED",
                OverallStatus="OK",
                LastError=None,
            )
            print(f"CLOUD_STAGE_OK snapshot={result.snapshot_id}")
        else:
            read_role(args.role_config, "STANDBY")
            snapshot_id = latest_cloud_snapshot_id(args.cloud_root) if args.snapshot == "latest" else args.snapshot
            result = receive_snapshot(args.cloud_root, args.cache_root, snapshot_id)
            if args.rehearse:
                rehearse_restore(args.cache_root, snapshot_id, args.work_root)
            update_health(
                args.health,
                LastReplicaReceive=_utc_now(),
                LastVerifiedBackup=_utc_now(),
                LatestSnapshotId=result.snapshot_id,
                DatabaseBytes=result.database_bytes,
                MediaFiles=result.media_files,
                CloudFolderAvailable=True,
                CloudStatus="RECEIVED",
                OverallStatus="OK",
                LastError=None,
            )
            suffix = " rehearsal=ok" if args.rehearse else ""
            print(f"REPLICA_RECEIVE_OK snapshot={result.snapshot_id}{suffix}")
        return 0
    except (BackupError, OSError, ValueError, sqlite3.Error) as exc:
        update_health(args.health, OverallStatus="ATTENTION", LastError=str(exc))
        print(f"BACKUP_TRANSPORT_ERROR reason={exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
