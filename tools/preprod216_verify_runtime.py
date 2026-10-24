"""Read-only aggregate and ownership verification for the isolated #216 runtime.

Executed inside its backend container; does not enumerate user names, prompts,
private paths, credentials or media bytes. Fails closed on count drift.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import sqlite3

EXPECTED = {
    "users": 59,
    "auth_passwords": 26,
    "images": 1941,
    "videos": 59,
    "jobs": 1842,
    "feed_publications": 96,
    "feed_reactions": 1357,
    "phone_chat_threads": 18,
    "phone_chat_messages": 90,
}
FORBIDDEN_SETTINGS = (
    "bot_integrations", "bot_diagnostics", "mail_provider_unisender",
    "yookassa", "social_syndication",
)


def verify(database: Path, media: Path, receipt_path: Path) -> dict:
    if not database.is_file() or not media.is_dir() or not receipt_path.is_file():
        raise RuntimeError("PREPROD216_VOLUME_MISSING")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("snapshot_id") != "20261024T082359.324871Z":
        raise RuntimeError("RECEIPT_SNAPSHOT_MISMATCH")
    # Pre-start/post-stop volume audit: never request WAL/SHM writes on a read-only mount.
    db = sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=5)
    try:
        db.execute("PRAGMA query_only=ON")
        counts = {
            name: db.execute("SELECT count(*) FROM " + name).fetchone()[0]
            for name in EXPECTED
        }
        if any(counts[name] != value for name, value in EXPECTED.items()):
            raise RuntimeError("PREPROD216_HISTORICAL_COUNTS_DRIFT")
        imported_sessions = db.execute(
            "SELECT count(*) FROM auth_sessions WHERE revoked_at IS NULL"
        ).fetchone()[0]
        if imported_sessions:
            raise RuntimeError("IMPORTED_SESSIONS_NOT_REVOKED")
        for key in FORBIDDEN_SETTINGS:
            if db.execute(
                "SELECT count(*) FROM admin_settings WHERE key=?", (key,)
            ).fetchone()[0]:
                raise RuntimeError("ACTIVE_SIDE_EFFECT_CONFIGURATION_RESTORED")
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("PREPROD216_SQLITE_QUICK_CHECK_FAILED")
        published = db.execute(
            "SELECT count(*) FROM feed_publications WHERE status='published'"
        ).fetchone()[0]
    finally:
        db.close()

    # This separate own-volume receipt documents exactly one replacement for
    # a historically missing private WebP. Original 2564 source media remain.
    derived = 0
    thumb_receipt = receipt_path.with_name("preprod216_thumbnail_repair_receipt.json")
    if thumb_receipt.exists():
        detail = json.loads(thumb_receipt.read_text(encoding="utf-8"))
        relative = PurePosixPath(detail["relative_media_path"])
        if (relative.is_absolute() or ".." in relative.parts
                or not detail.get("derived_from_existing_same_owner_thumbnail")
                or not detail.get("applied")
                or detail.get("target_size") != [384, 384]):
            raise RuntimeError("PREPROD216_INVALID_REPAIR_RECEIPT")
        target = (media / Path(*relative.parts)).resolve(strict=True)
        try:
            target.relative_to(media.resolve(strict=True))
        except ValueError as exc:
            raise RuntimeError("PREPROD216_UNOWNED_REPAIR_PATH") from exc
        if not target.is_file() or target.is_symlink():
            raise RuntimeError("PREPROD216_REPAIR_FILE_MISSING")
        if sha256(target.read_bytes()).hexdigest() != detail["sha256"]:
            raise RuntimeError("PREPROD216_REPAIR_SHA_MISMATCH")
        if target.stat().st_size != detail["bytes"]:
            raise RuntimeError("PREPROD216_REPAIR_SIZE_MISMATCH")
        derived = 1
    media_files = sum(file.is_file() for file in media.rglob("*"))
    if media_files != receipt["copied_media_files"] + derived:
        raise RuntimeError("PREPROD216_MEDIA_COUNT_DRIFT")
    return {
        "ok": True,
        "snapshot_id": receipt["snapshot_id"],
        "historic_counts": counts,
        "feed_published": published,
        "media_files": media_files,
        "derived_private_thumbnail_count": derived,
        "historical_sessions_active": imported_sessions,
        "copied_media_bytes": receipt["copied_media_bytes"],
        "copied_source_sha256": receipt["source_database_sha256"],
        "secrets_reported": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--media", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.database, args.media, args.receipt)))
