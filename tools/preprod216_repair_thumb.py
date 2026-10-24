"""Repair exactly one confirmed missing private thumbnail, inside the owned clone.

The source DB is only read, and an existing same-owner image thumbnail is the
sole input. No historical row, baseline file, or other image may be modified.
The default is dry-run; --apply is an explicit, narrowly scoped operation.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import tempfile
from urllib.parse import parse_qsl, unquote, urlsplit

from PIL import Image, ImageOps


def media_path(media: Path, url: str | None,
               owner: str | None = None) -> Path | None:
    if not url or not isinstance(url, str):
        return None
    parts = urlsplit(url)
    if parts.scheme or parts.netloc or parts.fragment:
        return None
    # Historical private media URLs carry userId; never discard it blindly.
    if parts.query:
        params = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
        if (len(params) != 1 or params[0][0] != "userId"
                or owner is None or params[0][1] != str(owner)):
            return None
    raw = unquote(parts.path)
    if raw.startswith("/api/media/"):
        raw = raw[len("/api/media/"):]
    elif raw.startswith("/media/"):
        raw = raw[len("/media/"):]
    else:
        return None
    if "\\" in raw or "%" in raw:
        return None
    rel = PurePosixPath(raw)
    if not raw or rel.is_absolute() or any(p in (".", "..") for p in rel.parts):
        return None
    resolved_root = media.resolve(strict=True)
    candidate = (resolved_root / Path(*rel.parts)).resolve(strict=False)
    try:
        candidate.relative_to(resolved_root)
    except ValueError:
        return None
    return candidate


def find_repair(database: Path, media: Path) -> tuple[Path, Path, tuple[int, int]]:
    db = sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True)
    db.execute("PRAGMA query_only=ON")
    try:
        rows = db.execute(
            """SELECT s.thumb_url, s.thumb_width, s.thumb_height,
                      s.user_id, i.user_id, i.thumbnail_url, i.deleted_at
               FROM image_sources AS s
               INNER JOIN images AS i ON s.image_id=i.id
               WHERE s.library_deleted_at IS NULL AND s.thumb_url IS NOT NULL"""
        )
        missing = []
        for url, width, height, owner1, owner2, preview, deleted in rows:
            target = media_path(media, url, owner=owner1)
            if target is not None and not target.exists():
                missing.append((target, width, height, owner1, owner2, preview, deleted))
    finally:
        db.close()
    if len(missing) != 1:
        raise RuntimeError("EXPECTED_ONE_MISSING_THUMBNAIL")
    target, width, height, owner1, owner2, preview, deleted = missing[0]
    if (owner1 != owner2 or deleted is not None or
            not isinstance(width, int) or not isinstance(height, int) or
            not 32 <= width <= 768 or not 32 <= height <= 768 or
            target.suffix.lower() != ".webp"):
        raise RuntimeError("UNSAFE_THUMBNAIL_OWNERSHIP_OR_DIMENSIONS")
    source = media_path(media, preview, owner=owner1)
    if (source is None or not source.is_file() or source.is_symlink() or
            source == target):
        raise RuntimeError("SAME_OWNER_SOURCE_THUMBNAIL_UNAVAILABLE")
    with Image.open(source) as check:
        check.verify()
    return source, target, (width, height)


def repair(database: Path, media: Path, apply: bool,
           receipt_out: Path | None = None) -> dict:
    source, target, dims = find_repair(database, media)
    outcome = {
        "expected_missing": 1,
        "same_owner_source_available": True,
        "target_size": list(dims),
        "applied": False,
    }
    if not apply:
        return outcome
    if receipt_out is not None and receipt_out.exists():
        raise RuntimeError("REFUSE_EXISTING_RECEIPT")
    if target.exists():
        raise RuntimeError("REFUSE_EXISTING_TARGET")
    # Only a writable candidate media volume is ever mounted here.
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.parent.resolve() != target.parent:
        raise RuntimeError("THUMBNAIL_PARENT_SYMLINK")
    fd, temp = tempfile.mkstemp(prefix=".preprod216-thumb-", suffix=".webp",
                                dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream, Image.open(source) as im:
            copied = ImageOps.fit(im.convert("RGB"), dims,
                                  method=Image.Resampling.LANCZOS)
            copied.save(stream, format="WEBP", quality=82, method=6)
            stream.flush()
            os.fsync(stream.fileno())
        stat = source.stat()
        os.chown(temp, stat.st_uid, stat.st_gid)
        os.chmod(temp, 0o640)
        with Image.open(temp) as check:
            check.verify()
        # Atomic create, not replace: never overwrite even on a race.
        os.link(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    actual = target.read_bytes()
    with Image.open(target) as result:
        if result.size != dims:
            raise RuntimeError("RESTORED_THUMBNAIL_WRONG_DIMENSIONS")
    outcome.update(applied=True, bytes=len(actual),
                   sha256=sha256(actual).hexdigest())
    if receipt_out is not None:
        # Local-only private receipt: a precise path is needed for future
        # readback, but never emit it to stdout, GitHub or an API response.
        detail = dict(outcome)
        detail["relative_media_path"] = target.relative_to(media.resolve()).as_posix()
        detail["derived_from_existing_same_owner_thumbnail"] = True
        if not receipt_out.parent.is_dir() or receipt_out.parent.is_symlink():
            raise RuntimeError("UNSAFE_REPAIR_RECEIPT_DESTINATION")
        with receipt_out.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(detail, ensure_ascii=False, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        owner = receipt_out.parent.stat()
        os.chown(receipt_out, owner.st_uid, owner.st_gid)
        os.chmod(receipt_out, 0o640)
    return outcome


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--media", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--receipt-out", type=Path)
    args = parser.parse_args()
    if args.apply and args.receipt_out is None:
        parser.error("--apply requires --receipt-out on the owned data volume")
    print(json.dumps(repair(args.database, args.media, args.apply,
                            args.receipt_out)))
