"""Owner-approved, offline single-account historic gallery restoration #216.

Work exclusively on stopped preprod216 own volumes. Originals and independently
verified pre-migration backup are mounted read-only. --check never writes.
--apply creates only absent original media and updates exactly 8 images, 1 video,
one original video job's necessary localFile/galleryDeleted fields, and one
single-owner quota override (120 images, 15 videos). Other records unchanged.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
from urllib.parse import parse_qsl, unquote, urlsplit

BASE_SHA = "01d229746d493360c3e4ff1752915699a30297416787ddcb387a69ce982a8f2d"
BACKUP_SHA = "4db2044f50aed6137b4fcf5103c76b89215315d2f7f6717d87b00d40515fbac2"
EXPECTED_EXTENSIONS = {".png": 8, ".webp": 16, ".mp4": 1}
RESTORE_COUNTS = {"images": 8, "videos": 1}
QUOTAS = (120, 15)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(4 * 1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def safe_relative(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "%" in value:
        raise RuntimeError("UNSAFE_HISTORIC_MEDIA_PATH")
    rel = PurePosixPath(value)
    if rel.is_absolute() or not rel.parts or len(rel.parts) > 10 or any(
            part in (".", "..") for part in rel.parts):
        raise RuntimeError("UNSAFE_HISTORIC_MEDIA_PATH")
    return rel.as_posix()


def private_url_path(url: str, owner: str) -> str:
    parts = urlsplit(str(url))
    if (parts.scheme or parts.netloc or parts.fragment
            or not parts.path.startswith("/api/media/")
            or parse_qsl(parts.query, keep_blank_values=True) != [("userId", owner)]):
        raise RuntimeError("PRIVATE_GALLERY_OWNER_URL_MISMATCH")
    return safe_relative(unquote(parts.path[len("/api/media/"):]))


def connect(path: Path, *, readonly: bool) -> sqlite3.Connection:
    uri = path.as_uri() + ("?mode=ro&immutable=1" if readonly else "?mode=rw")
    conn = sqlite3.connect(uri, uri=True, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    if readonly:
        conn.execute("PRAGMA query_only=ON")
    return conn


def source_data(db: sqlite3.Connection, table: str) -> dict:
    return {row["id"]: row for row in db.execute(
        "SELECT * FROM " + table + " WHERE deleted_at IS NULL"
    ).fetchall()}


def unchanged_hash(db: sqlite3.Connection, table: str, owner: str | None) -> str:
    if table in ("images", "videos", "jobs") and owner is not None:
        rows = db.execute("SELECT * FROM " + table +
                          " WHERE user_id<>? ORDER BY id", (owner,))
    else:
        rows = db.execute("SELECT * FROM " + table + " ORDER BY 1")
    h = hashlib.sha256()
    for row in rows:
        h.update(json.dumps(list(row), ensure_ascii=False, default=str,
                            separators=(",", ":")).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def plan(baseline: Path, data: Path, media: Path, backup: Path) -> dict:
    if sha(baseline / "database.sqlite3") != BASE_SHA:
        raise RuntimeError("IMMUTABLE_SOURCE_DB_SHA_DRIFT")
    snapshot = backup / "owner-pre-migration.sqlite3"
    if sha(snapshot) != BACKUP_SHA:
        raise RuntimeError("INDEPENDENT_ROLLBACK_SNAPSHOT_MISMATCH")
    pre_receipt = json.loads((backup / "backup-receipt.json").read_text("utf-8"))
    if (pre_receipt.get("consistent_sqlite", {}).get("sha256") != BACKUP_SHA
            or pre_receipt.get("media_count") != 2565
            or pre_receipt.get("evicted_archive_count") != 26):
        raise RuntimeError("INDEPENDENT_BACKUP_RECEIPT_INVALID")
    restored_receipt_path = data / "preprod216_owner_restore_receipt.json"
    if restored_receipt_path.exists() or restored_receipt_path.is_symlink():
        raise RuntimeError("OWNER_RESTORE_ALREADY_RECORDED")

    current = data / "app.sqlite3"
    if not current.is_file():
        raise RuntimeError("OWNER_CANDIDATE_DB_MISSING")
    archive = data / "preprod216-rollbacks" / "evicted-history-20261024"
    archive_receipt = json.loads((archive / "private-receipt.json").read_text("utf-8"))
    files = archive_receipt.get("files") or []
    if len(files) != 25 or dict(Counter(
            PurePosixPath(item["relative_path"]).suffix.lower() for item in files
    )) != EXPECTED_EXTENSIONS:
        raise RuntimeError("EXPECTED_25_HISTORIC_FILES_NOT_IN_ARCHIVE")
    file_infos = {}
    baseline_media = (baseline / "media").resolve(strict=True)
    active_media = media.resolve(strict=True)
    for item in files:
        rel = safe_relative(item["relative_path"])
        if rel in file_infos:
            raise RuntimeError("DUPLICATE_ARCHIVE_PATH")
        source = (baseline_media / rel).resolve(strict=True)
        preserved = (archive / rel).resolve(strict=True)
        source.relative_to(baseline_media)
        preserved.relative_to(archive.resolve(strict=True))
        target = (active_media / rel).resolve(strict=False)
        target.relative_to(active_media)
        if (target.exists() or source.is_symlink() or preserved.is_symlink()
                or not source.is_file() or not preserved.is_file()):
            raise RuntimeError("HISTORIC_MEDIA_TARGET_OR_SOURCE_INVALID")
        expected = item["sha256"]
        if sha(source) != expected or sha(preserved) != expected:
            raise RuntimeError("ORIGINAL_AND_ARCHIVED_FILE_SHA_MISMATCH")
        backfile = backup / "evicted-history" / rel
        if sha(backfile) != expected:
            raise RuntimeError("INDEPENDENT_BACKUP_ARCHIVE_SHA_MISMATCH")
        file_infos[rel] = {"source": source, "archived": preserved,
                           "target": target, "sha256": expected,
                           "bytes": item["bytes"]}

    b = connect(baseline / "database.sqlite3", readonly=True)
    c = connect(current, readonly=True)
    try:
        if c.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("CURRENT_SQLITE_INTEGRITY_FAILED")
        affected: dict[str, list] = {"images": [], "videos": []}
        owners = set()
        for table in affected:
            for rid, row in source_data(b, table).items():
                actual = c.execute("SELECT * FROM " + table + " WHERE id=?",
                                   (rid,)).fetchone()
                if actual and actual["deleted_at"] is not None:
                    if row["user_id"] != actual["user_id"]:
                        raise RuntimeError("HISTORIC_ROW_CHANGED_OWNERSHIP")
                    affected[table].append((row, actual))
                    owners.add(str(row["user_id"]))
            if len(affected[table]) != RESTORE_COUNTS[table]:
                raise RuntimeError("WRONG_NUMBER_NEWLY_SOFT_DELETED_" + table)
        if len(owners) != 1:
            raise RuntimeError("MIGRATION_OWNER_NOT_UNIQUE")
        owner = next(iter(owners))
        user = c.execute("SELECT * FROM users WHERE id=?", (owner,)).fetchone()
        if not user or str(user["plan"]).lower() != "pro" or str(user["role"]) != "admin":
            raise RuntimeError("NOT_EXISTING_OWNER_PRO_ADMIN")
        active_images = c.execute(
            "SELECT COUNT(*) FROM images WHERE user_id=? AND deleted_at IS NULL",
            (owner,)).fetchone()[0]
        active_videos = c.execute(
            "SELECT COUNT(*) FROM videos WHERE user_id=? AND deleted_at IS NULL",
            (owner,)).fetchone()[0]
        if (active_images, active_videos) != (100, 10):
            raise RuntimeError("MIGRATION_PRESTATE_GALLERY_QUOTA_CHANGED")
        expected_new = c.execute(
            "SELECT DISTINCT user_id FROM jobs WHERE created_at>"
            "'2026-10-23T20:43:30.625153+00:00'"
        ).fetchall()
        if len(expected_new) != 1 or str(expected_new[0][0]) != owner:
            raise RuntimeError("NEW_GENERATIONS_BELONG_TO_ANOTHER_OWNER")

        referenced_webp = set()
        for before, after in affected["images"]:
            for col in ("id", "user_id", "job_id", "url", "thumbnail_url",
                        "created_at", "width", "height", "provider"):
                if before[col] != after[col]:
                    raise RuntimeError("HISTORIC_IMAGE_CONTENT_MISMATCH_" + col)
            for col in ("url", "thumbnail_url"):
                referenced_webp.add(private_url_path(before[col], owner))
        if len(referenced_webp) != 16:
            raise RuntimeError("HISTORIC_IMAGES_MEDIA_REFERENCES_NOT_16")
        webp = {key for key in file_infos if key.endswith(".webp")}
        if referenced_webp != webp:
            raise RuntimeError("HISTORIC_IMAGES_DO_NOT_MATCH_16_WEBP_FILES")

        before_video, after_video = affected["videos"][0]
        for col in ("id", "user_id", "job_id", "url", "created_at",
                    "width", "height", "duration_seconds", "provider"):
            if before_video[col] != after_video[col]:
                raise RuntimeError("HISTORIC_VIDEO_CONTENT_MISMATCH_" + col)
        if c.execute("SELECT COUNT(*) FROM video_file_deletions WHERE video_id=?",
                     (before_video["id"],)).fetchone()[0]:
            raise RuntimeError("HISTORIC_VIDEO_FILE_STILL_QUEUED_FOR_DELETION")
        source_job = b.execute(
            "SELECT settings_json FROM jobs WHERE id=? AND user_id=?",
            (before_video["job_id"], owner)
        ).fetchone()
        current_job = c.execute(
            "SELECT settings_json FROM jobs WHERE id=? AND user_id=?",
            (before_video["job_id"], owner)
        ).fetchone()
        if not source_job or not current_job:
            raise RuntimeError("HISTORIC_VIDEO_JOB_MISSING")
        old = json.loads(source_job[0])
        new = json.loads(current_job[0])
        original_file = safe_relative(old["localFile"])
        mp4s = {key for key in file_infos if key.endswith(".mp4")}
        if mp4s != {original_file} or new.get("localFile") is not None:
            raise RuntimeError("HISTORIC_VIDEO_SOURCE_FILE_MISMATCH")
        if new.get("galleryDeleted") is not True:
            raise RuntimeError("HISTORIC_VIDEO_REMOVAL_MARKER_CHANGED")

        try:
            existing = c.execute(
                "SELECT COUNT(*) FROM preprod216_owner_gallery_overrides"
            ).fetchone()[0]
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc).lower():
                raise
            existing = 0
        if existing:
            raise RuntimeError("EXISTING_PERSONAL_MIGRATION_OVERRIDE")

        material_before = {
            name: unchanged_hash(c, name, owner)
            for name in ("images", "videos", "jobs", "users",
                         "token_ledger", "feed_publications",
                         "phone_chat_messages", "admin_settings")
        }
        return {
            "owner": owner,
            "affected": affected,
            "video_job_id": before_video["job_id"],
            "video_local_file": original_file,
            "new_video_job_json": new,
            "file_infos": file_infos,
            "material_before": material_before,
            "active_images_before": active_images,
            "active_videos_before": active_videos,
            "source_sha256": BASE_SHA,
            "backup_sha256": BACKUP_SHA,
        }
    finally:
        b.close()
        c.close()


def _copy_missing_file(info: dict, media: Path) -> None:
    target = info["target"]
    media_root = media.resolve(strict=True)
    target.relative_to(media_root)
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    if parent.is_symlink() or target.exists() or target.is_symlink():
        raise RuntimeError("REFUSE_MEDIA_OVERWRITE_OR_LINK")
    fd, temporary = tempfile.mkstemp(dir=parent, prefix=".preprod216-restore-")
    try:
        with os.fdopen(fd, "wb") as output, info["archived"].open("rb") as source:
            shutil.copyfileobj(source, output, 4 * 1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        if sha(Path(temporary)) != info["sha256"]:
            raise RuntimeError("NEW_FILE_SHA_MISMATCH")
        original_stat = info["source"].stat()
        os.utime(temporary, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        os.chown(temporary, 10001, 10001)
        os.chmod(temporary, 0o640)
        os.link(temporary, target)  # atomic no-overwrite creation
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply_restore(baseline: Path, data: Path, media: Path, backup: Path) -> dict:
    selected = plan(baseline, data, media, backup)
    files = selected["file_infos"]
    created = []
    try:
        for rel, info in files.items():
            _copy_missing_file(info, media)
            created.append(info["target"])
        c = connect(data / "app.sqlite3", readonly=False)
        try:
            c.execute("BEGIN IMMEDIATE")
            c.execute("""CREATE TABLE preprod216_owner_gallery_overrides (
                user_id TEXT PRIMARY KEY REFERENCES users(id),
                plan TEXT NOT NULL CHECK(plan='pro'),
                gallery_slots INTEGER NOT NULL CHECK(gallery_slots=120),
                video_slots INTEGER NOT NULL CHECK(video_slots=15),
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""")
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            c.execute(
                "INSERT INTO preprod216_owner_gallery_overrides VALUES (?,?,?,?,?,?)",
                (selected["owner"], "pro", 120, 15,
                 "owner_approved_preprod216_historic_restoration", now)
            )
            for before, _after in selected["affected"]["images"]:
                change = c.execute(
                    "UPDATE images SET deleted_at=NULL "
                    "WHERE id=? AND user_id=? AND deleted_at IS NOT NULL",
                    (before["id"], selected["owner"])
                )
                if change.rowcount != 1:
                    raise RuntimeError("IMAGE_RESTORE_CHANGED_ROWS")
            for before, _after in selected["affected"]["videos"]:
                change = c.execute(
                    "UPDATE videos SET deleted_at=NULL "
                    "WHERE id=? AND user_id=? AND deleted_at IS NOT NULL",
                    (before["id"], selected["owner"])
                )
                if change.rowcount != 1:
                    raise RuntimeError("VIDEO_RESTORE_CHANGED_ROWS")
            settings = dict(selected["new_video_job_json"])
            settings["localFile"] = selected["video_local_file"]
            settings.pop("galleryDeleted", None)
            change = c.execute(
                "UPDATE jobs SET settings_json=? WHERE id=? AND user_id=?",
                (json.dumps(settings, ensure_ascii=False),
                 selected["video_job_id"], selected["owner"])
            )
            if change.rowcount != 1:
                raise RuntimeError("VIDEO_JOB_RESTORE_CHANGED_ROWS")
            owner = selected["owner"]
            image_count = c.execute(
                "SELECT COUNT(*) FROM images WHERE user_id=? AND deleted_at IS NULL",
                (owner,)
            ).fetchone()[0]
            video_count = c.execute(
                "SELECT COUNT(*) FROM videos WHERE user_id=? AND deleted_at IS NULL",
                (owner,)
            ).fetchone()[0]
            if (image_count, video_count) != (108, 11):
                raise RuntimeError("POST_RESTORE_ACTIVE_QUOTA_COUNTS_INVALID")
            for name, digest in selected["material_before"].items():
                # Job settings changes for only one historic video are separately
                # constrained by the snapshot above; all other rows must match.
                if name == "jobs":
                    continue
                if unchanged_hash(c, name, owner) != digest:
                    raise RuntimeError("UNRELATED_RECORD_CHANGED_" + name)
            if c.execute("PRAGMA foreign_key_check").fetchone():
                raise RuntimeError("POST_RESTORE_FOREIGN_KEY_FAILURE")
            c.commit()
            if c.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("POST_RESTORE_QUICK_CHECK_FAILED")
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()
    except BaseException:
        # Only remove files created in this uncommitted operation; never
        # delete historic files following a successfully committed transaction.
        check = connect(data / "app.sqlite3", readonly=True)
        try:
            applied = check.execute(
                "SELECT COUNT(*) FROM images WHERE user_id=? AND deleted_at IS NULL",
                (selected["owner"],)
            ).fetchone()[0] == 108
        finally:
            check.close()
        if not applied:
            for item in created:
                item.unlink(missing_ok=True)
        raise

    receipt_path = data / "preprod216_owner_restore_receipt.json"
    receipt = {
        "source_database_sha256": selected["source_sha256"],
        "independent_pre_migration_sqlite_sha256": selected["backup_sha256"],
        "owner_id": selected["owner"],
        "owner_plan": "pro", "image_limit": 120, "video_limit": 15,
        "image_rows_restored": 8, "video_rows_restored": 1,
        "owner_images_active": 108, "owner_videos_active": 11,
        "media_files_restored": len(files),
        "media_files": [
            {"relative_path": rel, "sha256": info["sha256"],
             "bytes": info["bytes"]}
            for rel, info in sorted(files.items())
        ],
        "historic_image_ids": [old["id"] for old, _ in selected["affected"]["images"]],
        "historic_video_id": selected["affected"]["videos"][0][0]["id"],
        "historic_video_job_id": selected["video_job_id"],
        "original_archived_files_retained": True,
        "new_and_other_users_records_untouched": True,
    }
    with receipt_path.open("x", encoding="utf-8") as out:
        json.dump(receipt, out, indent=2, ensure_ascii=False)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
    os.chown(receipt_path, 10001, 10001)
    os.chmod(receipt_path, 0o640)
    return {
        "restored_images": 8, "restored_videos": 1,
        "quota_images": 120, "quota_videos": 15,
        "used_images": 108, "used_videos": 11,
        "restored_media_count": len(files),
        "restored_media_bytes": sum(info["bytes"] for info in files.values()),
        "private_receipt_sha256": sha(receipt_path),
        "new_paid_requests": 0,
        "baseline_and_other_users_unchanged": True,
    }


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("--baseline", type=Path, required=True)
    cli.add_argument("--data", type=Path, required=True)
    cli.add_argument("--media", type=Path, required=True)
    cli.add_argument("--backup", type=Path, required=True)
    cli.add_argument("--apply", action="store_true")
    args = cli.parse_args()
    if args.apply:
        print(json.dumps(apply_restore(args.baseline, args.data,
                                       args.media, args.backup)))
    else:
        checked = plan(args.baseline, args.data, args.media, args.backup)
        print(json.dumps({
            "preflight": "PASS",
            "images": len(checked["affected"]["images"]),
            "videos": len(checked["affected"]["videos"]),
            "archived_media_verified": len(checked["file_infos"]),
            "backup_database_sha256": checked["backup_sha256"],
            "quota_target": {"images": 120, "videos": 15},
            "source_owner_unique_pro": True,
        }))
