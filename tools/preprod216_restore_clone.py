"""Copy verified October restore into fresh, exclusively owned preprod216 volumes.

Run only as a one-shot network-disabled container with the baseline bind read-only.
Never reads provider secrets, never prints private database rows, and refuses
nonempty destination volumes. Revocations affect only the copied SQLite.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat


OWNED_TABLES = (
    "users", "auth_passwords", "auth_identities", "auth_sessions",
    "images", "videos", "jobs", "feed_publications", "feed_reactions",
    "phone_chat_threads", "phone_chat_messages",
)
EXPECTED_COUNTS = {
    "users": 59, "auth_passwords": 26, "images": 1941, "videos": 59,
    "jobs": 1842, "feed_publications": 96, "feed_reactions": 1357,
    "phone_chat_threads": 18, "phone_chat_messages": 90,
}
DISABLED_SIDE_EFFECT_SETTINGS = (
    "bot_integrations", "bot_diagnostics", "mail_provider_unisender",
    "yookassa", "social_syndication",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ownerize(path: Path, directory: bool = False) -> None:
    if os.name == "posix":
        os.chown(path, 10001, 10001)
    path.chmod(0o750 if directory else 0o640)


def copy_tree_checked(source: Path, destination: Path) -> tuple[int, int]:
    if not source.is_dir() or source.is_symlink():
        raise RuntimeError("SOURCE_TREE_INVALID")
    count = size = 0
    ownerize(destination, directory=True)
    for item in sorted(source.rglob("*")):
        if item.is_symlink():
            raise RuntimeError("SOURCE_SYMLINK_NOT_ALLOWED")
        relative = item.relative_to(source)
        target = destination / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=False)
            ownerize(target, directory=True)
            continue
        if not item.is_file():
            raise RuntimeError("SOURCE_SPECIAL_FILE_NOT_ALLOWED")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item, target)
        ownerize(target)
        if sha256(item) != sha256(target):
            raise RuntimeError("COPIED_MEDIA_SHA_MISMATCH")
        count += 1
        size += item.stat().st_size
    return count, size


def clone(source: Path, receipt_path: Path, data: Path, media: Path, seed: Path) -> dict:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("snapshot_id") != "20261024T082359.324871Z":
        raise RuntimeError("SNAPSHOT_ID_MISMATCH")
    database = source / "database.sqlite3"
    seed_source = source / "application-assets" / "backend" / "seed" / "feed"
    expected_db = receipt["database_sha256"]
    if sha256(database) != expected_db:
        raise RuntimeError("BASELINE_DB_SHA_MISMATCH")
    for target in (data, media, seed):
        if not target.is_dir() or target.is_symlink() or any(target.iterdir()):
            raise RuntimeError("DESTINATION_VOLUME_NOT_EMPTY")
    candidate_db = data / "app.sqlite3"
    shutil.copyfile(database, candidate_db)
    if sha256(candidate_db) != expected_db:
        raise RuntimeError("COPIED_DB_SHA_MISMATCH")
    ownerize(data, directory=True)
    ownerize(candidate_db)

    media_files, media_bytes = copy_tree_checked(source / "media", media)
    if (media_files != receipt["media_count"]
            or media_bytes != receipt["media_bytes"]):
        raise RuntimeError("BASELINE_MEDIA_COUNT_OR_SIZE_MISMATCH")
    seed_files, _ = copy_tree_checked(seed_source, seed)

    conn = sqlite3.connect(str(candidate_db), timeout=20)
    try:
        counts = {
            name: conn.execute("SELECT count(*) FROM " + name).fetchone()[0]
            for name in OWNED_TABLES
        }
        if any(counts[k] != value for k, value in EXPECTED_COUNTS.items()):
            raise RuntimeError("BASELINE_TABLE_COUNT_MISMATCH")
        if conn.execute("PRAGMA user_version").fetchone()[0] != 7:
            raise RuntimeError("BASELINE_SCHEMA_VERSION_MISMATCH")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("CANDIDATE_INTEGRITY_FAILED")
        if conn.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("CANDIDATE_FK_FAILED")

        now = datetime.now(timezone.utc).isoformat()
        # Preserve the session audit rows but deny all imported live cookies.
        with conn:
            revoked = conn.execute(
                """UPDATE auth_sessions
                   SET revoked_at=?, revoke_reason='preprod216_clone_revocation'
                   WHERE revoked_at IS NULL""",
                (now,),
            ).rowcount
            settings_removed = conn.execute(
                "DELETE FROM admin_settings WHERE key IN (" +
                ",".join("?" for _ in DISABLED_SIDE_EFFECT_SETTINGS) + ")",
                DISABLED_SIDE_EFFECT_SETTINGS,
            ).rowcount
        if conn.execute(
                "SELECT count(*) FROM auth_sessions WHERE revoked_at IS NULL"
                ).fetchone()[0] != 0:
            raise RuntimeError("IMPORT_SESSIONS_NOT_REVOKED")
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("POST_REVOCATION_SQLITE_FAILED")
        if any(
            conn.execute("SELECT count(*) FROM " + k).fetchone()[0] != value
            for k, value in EXPECTED_COUNTS.items()
        ):
            raise RuntimeError("HISTORIC_COUNTS_CHANGED")
    finally:
        conn.close()
    ownerize(candidate_db)
    result = {
        "snapshot_id": receipt["snapshot_id"],
        "source_database_sha256": expected_db,
        "candidate_database_sha256": sha256(candidate_db),
        "source_media_count": receipt["media_count"],
        "copied_media_files": media_files,
        "copied_media_bytes": media_bytes,
        "seed_files": seed_files,
        "session_rows_newly_revoked": revoked,
        "still_active_imported_sessions": 0,
        "unsafe_side_effect_settings_removed": settings_removed,
        "historic_counts": counts,
        "schema_version": 7,
        "verified": True,
    }
    receipt_out = data / "preprod216_clone_receipt.json"
    receipt_out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    ownerize(receipt_out)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--media", type=Path, required=True)
    parser.add_argument("--seed", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(clone(
        args.baseline, args.receipt, args.data, args.media, args.seed
    ), ensure_ascii=False))
