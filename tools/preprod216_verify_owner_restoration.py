"""Read-only independent receipt check for the one-account #216 migration."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def db(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA query_only=ON")
    return c


def verify(data: Path, media: Path, backup: Path, baseline: Path):
    receipt = json.loads(
        (data / "preprod216_owner_restore_receipt.json").read_text("utf-8")
    )
    initial = json.loads((backup / "backup-receipt.json").read_text("utf-8"))
    archived = json.loads(
        (data / "preprod216-rollbacks/evicted-history-20261024/private-receipt.json")
        .read_text("utf-8")
    )
    if (initial["consistent_sqlite"]["sha256"] != receipt[
            "independent_pre_migration_sqlite_sha256"]
            or len(receipt["media_files"]) != 25
            or archived["archived_files"] != 25):
        raise RuntimeError("INDEPENDENT_BACKUP_OR_RESTORE_RECEIPT_INVALID")
    old_media = {e["relative_path"]: e["sha256"] for e in archived["files"]}
    if old_media != {e["relative_path"]: e["sha256"]
                     for e in receipt["media_files"]}:
        raise RuntimeError("RESTORE_NOT_EQUAL_TO_PRESERVED_ORIGINAL_ARCHIVE")
    original_root = (baseline / "media").resolve(strict=True)
    current_root = media.resolve(strict=True)
    for name, value in old_media.items():
        current_file = (current_root / name).resolve(strict=True)
        original_file = (original_root / name).resolve(strict=True)
        current_file.relative_to(current_root)
        original_file.relative_to(original_root)
        if hash_file(current_file) != value or hash_file(original_file) != value:
            raise RuntimeError("RESTORED_FILE_SHA_OR_SOURCE_CHANGED")
    media_count = sum(f.is_file() for f in current_root.rglob("*"))
    if media_count != 2590:
        raise RuntimeError("MIGRATED_MEDIA_TOTAL_UNEXPECTED")

    before = db(backup / "owner-pre-migration.sqlite3")
    after = db(data / "app.sqlite3")
    try:
        owner = receipt["owner_id"]
        overrides = after.execute(
            "SELECT user_id,plan,gallery_slots,video_slots "
            "FROM preprod216_owner_gallery_overrides"
        ).fetchall()
        if (len(overrides) != 1 or tuple(overrides[0]) !=
                (owner, "pro", 120, 15)):
            raise RuntimeError("MIGRATION_QUOTA_SCOPE_NOT_EXACT")
        for table, ids in (
                ("images", receipt["historic_image_ids"]),
                ("videos", [receipt["historic_video_id"]])):
            for identifier in ids:
                old = before.execute(
                    "SELECT * FROM " + table + " WHERE id=?", (identifier,)
                ).fetchone()
                restored = after.execute(
                    "SELECT * FROM " + table + " WHERE id=?", (identifier,)
                ).fetchone()
                if (not old or not restored or old["user_id"] != owner
                        or restored["user_id"] != owner
                        or old["deleted_at"] is None
                        or restored["deleted_at"] is not None
                        or any(old[key] != restored[key] for key in old.keys()
                               if key != "deleted_at")):
                    raise RuntimeError("HISTORIC_RECORD_CONTENT_MODIFIED_" + table)
        changed_job = receipt["historic_video_job_id"]
        old_settings = json.loads(before.execute(
            "SELECT settings_json FROM jobs WHERE id=?", (changed_job,)
        ).fetchone()[0])
        new_settings = json.loads(after.execute(
            "SELECT settings_json FROM jobs WHERE id=?", (changed_job,)
        ).fetchone()[0])
        with db(baseline / "database.sqlite3") as original:
            historical_settings = json.loads(original.execute(
                "SELECT settings_json FROM jobs WHERE id=?",
                (changed_job,)
            ).fetchone()[0])
        old_settings.pop("galleryDeleted", None)
        old_settings["localFile"] = historical_settings["localFile"]
        if old_settings != new_settings or "galleryDeleted" in new_settings:
            raise RuntimeError("VIDEO_JOB_METADATA_CHANGED_BEYOND_RESTORATION")
        for table, affected in (
                ("images", set(receipt["historic_image_ids"])),
                ("videos", {receipt["historic_video_id"]}),
                ("jobs", {changed_job})):
            remaining_old = {
                row["id"]: tuple(row) for row in before.execute(
                    "SELECT * FROM " + table) if row["id"] not in affected
            }
            remaining_new = {
                row["id"]: tuple(row) for row in after.execute(
                    "SELECT * FROM " + table) if row["id"] not in affected
            }
            if remaining_old != remaining_new:
                raise RuntimeError("NEW_OR_OTHER_USER_ROW_CHANGED_" + table)
        for table in ("users", "token_ledger", "admin_settings",
                      "feed_publications", "phone_chat_messages",
                      "image_sources"):
            a = before.execute("SELECT * FROM " + table + " ORDER BY 1").fetchall()
            b = after.execute("SELECT * FROM " + table + " ORDER BY 1").fetchall()
            if [tuple(x) for x in a] != [tuple(x) for x in b]:
                raise RuntimeError("OTHER_RECORD_MUTATED_" + table)
        counts = {}
        for table, count in (("users", 59), ("images", 1949), ("videos", 60),
                             ("jobs", 1851), ("token_ledger", 2887)):
            n = after.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            if n != count:
                raise RuntimeError("RESTORE_TABLE_COUNT_CHANGED_" + table)
            counts[table] = n
        images = after.execute(
            "SELECT COUNT(*) FROM images WHERE user_id=? AND deleted_at IS NULL",
            (owner,)
        ).fetchone()[0]
        videos = after.execute(
            "SELECT COUNT(*) FROM videos WHERE user_id=? AND deleted_at IS NULL",
            (owner,)
        ).fetchone()[0]
        if (images, videos) != (108, 11):
            raise RuntimeError("EFFECTIVE_GALLERY_NOT_RESTORED")
        if after.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("POST_RESTORE_DATABASE_CORRUPTED")
        return {
            "verified": True, "restored_image_rows": 8, "restored_video_rows": 1,
            "file_sha_match": 25, "media_count": media_count,
            "personal_quota": [120, 15], "owner_used": [images, videos],
            "other_user_and_billing_tables_equal_to_backup": True,
            "database_counts": counts,
            "new_cloud_paid_requests": 0,
        }
    finally:
        before.close()
        after.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for param in ("data", "media", "backup", "baseline"):
        parser.add_argument("--" + param, required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.data, args.media, args.backup, args.baseline)))
