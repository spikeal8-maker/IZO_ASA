"""Archive 25 user-owned historic media files displaced by quota eviction.

Run one-shot in a networkless Linux container. Original restore + candidate media
are read-only. The only writable mount is the preprod216 *owned* SQLite volume;
a private receipt and byte-for-byte archive are committed by atomic directory move.
No SQLite writes, session access, provider calls, or user-ID logging.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile

EXPECTED_BASELINE_SHA256 = "01d229746d493360c3e4ff1752915699a30297416787ddcb387a69ce982a8f2d"
EXPECTED_EXTENSIONS = {".png": 8, ".webp": 16, ".mp4": 1}
EXPECTED_LOST_IMAGES = 8
EXPECTED_LOST_VIDEOS = 1


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def read_table(conn: sqlite3.Connection, name: str):
    return {
        row[0]: (row[1], row[2])
        for row in conn.execute("SELECT id,user_id,deleted_at FROM " + name)
    }


def archive(baseline: Path, media: Path, data: Path) -> dict:
    source_database = baseline / "database.sqlite3"
    active_database = data / "app.sqlite3"
    source_media = (baseline / "media").resolve(strict=True)
    active_media = media.resolve(strict=True)
    storage = (data / "preprod216-rollbacks").resolve(strict=True)
    destination = storage / "evicted-history-20261024"
    if destination.exists() or destination.is_symlink():
        raise RuntimeError("EXISTING_PROTECTED_ARCHIVE_NOT_OVERWRITTEN")
    if sha256(source_database) != EXPECTED_BASELINE_SHA256:
        raise RuntimeError("ORIGINAL_DATABASE_SHA_MISMATCH")

    with sqlite3.connect(source_database.as_uri() + "?mode=ro&immutable=1", uri=True) as src:
        with sqlite3.connect(active_database.as_uri() + "?mode=ro", uri=True) as dst:
            lost_owners = set()
            for table, count in (("images", EXPECTED_LOST_IMAGES),
                                 ("videos", EXPECTED_LOST_VIDEOS)):
                before, after = read_table(src, table), read_table(dst, table)
                lost = [
                    key for key, (owner, deleted) in before.items()
                    if deleted is None and key in after
                    and after[key][1] is not None and after[key][0] == owner
                ]
                if len(lost) != count:
                    raise RuntimeError("HISTORIC_EVICTIONS_DRIFT_" + table)
                lost_owners.update(before[key][0] for key in lost)
            if len(lost_owners) != 1:
                raise RuntimeError("EVICTIONS_ARE_NOT_SINGLE_OWNER")
            if dst.execute("SELECT COUNT(*) FROM jobs WHERE status NOT IN ('completed','failed','cancelled')").fetchone()[0]:
                raise RuntimeError("NEW_JOBS_ACTIVE_REFUSE_ARCHIVE")

    source_files = {
        file.relative_to(source_media).as_posix(): file for file in source_media.rglob("*")
        if file.is_file()
    }
    current_files = {
        file.relative_to(active_media).as_posix() for file in active_media.rglob("*")
        if file.is_file()
    }
    missing = sorted(set(source_files) - current_files)
    kinds = dict(Counter(PurePosixPath(filename).suffix.lower() for filename in missing))
    if kinds != EXPECTED_EXTENSIONS:
        raise RuntimeError("UNEXPECTED_MISSING_MEDIA_SET")

    temp = Path(tempfile.mkdtemp(prefix=".history-archive-", dir=storage))
    os.chmod(temp, 0o700)
    receipt = []
    try:
        for name in missing:
            rel = PurePosixPath(name)
            if (rel.is_absolute() or ".." in rel.parts or "\\" in name
                    or not rel.parts or len(rel.parts) > 10):
                raise RuntimeError("UNSAFE_ARCHIVED_MEDIA_PATH")
            src = source_files[name]
            if src.is_symlink():
                raise RuntimeError("SYMLINK_IN_HISTORICAL_SOURCE")
            src.resolve(strict=True).relative_to(source_media)
            target = temp / Path(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(src, target)
            os.chmod(target, 0o600)
            if os.name == "posix":
                os.chown(target, 10001, 10001)
            digest = sha256(src)
            if sha256(target) != digest:
                raise RuntimeError("ARCHIVE_COPY_HASH_MISMATCH")
            receipt.append({"relative_path": name, "bytes": target.stat().st_size,
                            "sha256": digest})
        manifest = {
            "purpose": "Preprod216 historic media displaced by quota eviction",
            "source_database_sha256": EXPECTED_BASELINE_SHA256,
            "image_rows_newly_deleted": EXPECTED_LOST_IMAGES,
            "video_rows_newly_deleted": EXPECTED_LOST_VIDEOS,
            "archived_files": len(receipt),
            "extensions": kinds,
            "files": receipt,
        }
        private_receipt = temp / "private-receipt.json"
        private_receipt.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        os.chmod(private_receipt, 0o600)
        if os.name == "posix":
            os.chown(private_receipt, 10001, 10001)
        if os.name == "posix":
            for folder in [temp, *[d for d in temp.rglob("*") if d.is_dir()]]:
                os.chown(folder, 10001, 10001)
                os.chmod(folder, 0o700)
        os.rename(temp, destination)
        return {
            "archived": len(receipt),
            "extensions": kinds,
            "archive_bytes": sum(int(item["bytes"]) for item in receipt),
            "private_receipt_sha256": sha256(destination / "private-receipt.json"),
            "data_only_backup": True,
            "sqlite_unchanged": True,
            "private_gallery_visibility_unchanged": True,
        }
    finally:
        if temp.exists():
            shutil.rmtree(temp)


if __name__ == "__main__":
    import argparse
    cli = argparse.ArgumentParser()
    cli.add_argument("--baseline", type=Path, required=True)
    cli.add_argument("--media", type=Path, required=True)
    cli.add_argument("--data", type=Path, required=True)
    opt = cli.parse_args()
    print(json.dumps(archive(opt.baseline, opt.media, opt.data), sort_keys=True))
