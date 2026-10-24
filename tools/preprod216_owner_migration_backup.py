"""Consistent OFFLINE backup of current owner gallery before approved migration.

Read-only source mounts: candidate SQLite volume and candidate media volume.
Write destination: one new, empty, independently labelled rollback Docker volume.
No application DB writes, no files/sessions/secrets outside these three mounts.
"""
from __future__ import annotations

from collections import Counter
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3

EXPECTED = {"users": 59, "images": 1949, "videos": 60, "jobs": 1851,
            "token_ledger": 2887, "phone_chat_threads": 18,
            "phone_chat_messages": 90}


def digest(path: Path) -> str:
    out = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            out.update(chunk)
    return out.hexdigest()


def strict_copy(src: Path, dst: Path) -> dict:
    if not src.is_file() or src.is_symlink() or dst.exists():
        raise RuntimeError("SOURCE_NOT_REGULAR_OR_TARGET_EXISTS")
    dst.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if dst.parent.is_symlink():
        raise RuntimeError("DESTINATION_SYMLINK")
    with src.open("rb") as input_file, dst.open("xb") as output:
        shutil.copyfileobj(input_file, output, 4 * 1024 * 1024)
    os.chmod(dst, 0o600)
    expected = digest(src)
    if digest(dst) != expected:
        raise RuntimeError("BACKUP_FILE_SHA_MISMATCH")
    return {"bytes": dst.stat().st_size, "sha256": expected}


def strict_tree(src: Path, dst: Path) -> tuple[list[dict], int]:
    if not src.is_dir() or src.is_symlink():
        raise RuntimeError("BAD_BACKUP_SOURCE_DIRECTORY")
    if dst.exists():
        raise RuntimeError("BACKUP_TREE_ALREADY_EXISTS")
    dst.mkdir(parents=True, mode=0o700)
    entries = []
    total = 0
    for file in sorted(src.rglob("*")):
        if file.is_symlink():
            raise RuntimeError("SYMLINK_IN_BACKUP_SOURCE")
        rel = file.relative_to(src)
        if file.is_dir():
            (dst / rel).mkdir(parents=True, mode=0o700, exist_ok=True)
            continue
        if not file.is_file():
            raise RuntimeError("SPECIAL_FILE_IN_BACKUP_SOURCE")
        info = strict_copy(file, dst / rel)
        entries.append({"relative_path": rel.as_posix(), **info})
        total += info["bytes"]
    return entries, total


def backup(data: Path, media: Path, destination: Path) -> dict:
    if not data.is_dir() or not media.is_dir() or not destination.is_dir():
        raise RuntimeError("MISSING_OFFLINE_BACKUP_MOUNT")
    if any(destination.iterdir()):
        raise RuntimeError("REFUSE_NONEMPTY_INDEPENDENT_BACKUP_VOLUME")
    raw = destination / "sqlite-raw"
    raw.mkdir(mode=0o700)
    current = data / "app.sqlite3"
    raw_database = raw / "app.sqlite3"
    sqlite_files = {}
    for name in ("app.sqlite3", "app.sqlite3-wal", "app.sqlite3-shm"):
        source = data / name
        if source.exists():
            sqlite_files[name] = strict_copy(source, raw / name)
    if not raw_database.exists():
        raise RuntimeError("OWNER_SQLITE_NOT_PRESENT")
    snapshot = destination / "owner-pre-migration.sqlite3"
    with sqlite3.connect(raw_database) as conn, sqlite3.connect(snapshot) as output:
        conn.backup(output, pages=1024, sleep=0.05)
    os.chmod(snapshot, 0o600)

    db = sqlite3.connect(snapshot)
    try:
        for name, expected in EXPECTED.items():
            count = db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
            if count != expected:
                raise RuntimeError("PRE_MIGRATION_COUNT_MISMATCH_" + name)
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("PRE_MIGRATION_SQLITE_INTEGRITY_FAILURE")
        active = db.execute(
            "SELECT COUNT(*) FROM jobs WHERE status IN "
            "('queued','running','pending','submitting','processing','finalizing','in_progress')"
        ).fetchone()[0]
        if active:
            raise RuntimeError("PENDING_OWNER_JOBS_BLOCK_MAINTENANCE")
        before_counts = {
            name: db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
            for name in EXPECTED
        }
        owner_sessions = db.execute(
            "SELECT COUNT(*) FROM auth_sessions WHERE revoked_at IS NULL"
        ).fetchone()[0]
    finally:
        db.close()

    media_list, media_bytes = strict_tree(media, destination / "media")
    if len(media_list) != 2565:
        raise RuntimeError("UNEXPECTED_MEDIA_COUNT_DURING_BACKUP")

    archive = data / "preprod216-rollbacks" / "evicted-history-20261024"
    old_list, old_bytes = strict_tree(archive, destination / "evicted-history")
    prior_receipt = json.loads(
        (archive / "private-receipt.json").read_text(encoding="utf-8")
    )
    if prior_receipt.get("archived_files") != 25:
        raise RuntimeError("MISSING_PRIVATE_ORIGINAL_MEDIA_ARCHIVE")

    retained = {}
    for name in ("preprod216_clone_receipt.json",
                 "preprod216_thumbnail_repair_receipt.json"):
        source = data / name
        if not source.is_file():
            raise RuntimeError("PRIOR_CANDIDATE_RECEIPT_MISSING")
        retained[name] = strict_copy(source, destination / name)

    snapshot_sha = digest(snapshot)
    manifest = {
        "kind": "IZO_ASA_PREPROD216_OWNER_MIGRATION_OFFLINE_BACKUP",
        "source_compose_project": "izo-asa-preprod-d2r2-001",
        "source_revision": "6391dad9deaac50dee77843543e81da1317dff19",
        "baseline_unmodified": True,
        "source_sqlite_files": sqlite_files,
        "consistent_sqlite": {
            "name": snapshot.name, "bytes": snapshot.stat().st_size,
            "sha256": snapshot_sha, "counts": before_counts,
            "still_live_sessions": owner_sessions,
        },
        "media_count": len(media_list), "media_bytes": media_bytes,
        "media": media_list,
        "evicted_archive_count": len(old_list),
        "evicted_archive_bytes": old_bytes, "evicted_archive": old_list,
        "retained_receipts": retained,
        "restoration_performed": False,
    }
    receipt = destination / "backup-receipt.json"
    with receipt.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(receipt, 0o600)
    return {
        "backup_verified": True,
        "backup_sqlite_bytes": snapshot.stat().st_size,
        "backup_sqlite_sha256": snapshot_sha,
        "media_copied": len(media_list),
        "media_bytes": media_bytes,
        "evicted_archive_files_backed_up": len(old_list),
        "backup_receipt_sha256": digest(receipt),
        "active_generation_jobs": 0,
        "source_data_volume_unchanged": True,
    }


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("--data", required=True, type=Path)
    cli.add_argument("--media", required=True, type=Path)
    cli.add_argument("--destination", required=True, type=Path)
    args = cli.parse_args()
    print(json.dumps(backup(args.data, args.media, args.destination),
                     sort_keys=True))
