from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

import gallery_original_audit
import main
from media_storage_audit import _bytes_fmt, _media_rel_from_url


def _safe_target_rel(source_rel: str) -> str:
    source = Path(Path(source_rel.replace("\\", "/")).name)
    base = source.with_suffix(".webp")
    target = base
    i = 1
    while (main.MEDIA / target).exists():
        target = source.with_name(f"{source.stem}_optimized_{i}.webp")
        i += 1
    return target.as_posix()


def _active_image_rows() -> list[Any]:
    with main.db() as conn:
        image_columns = {row["name"] for row in conn.execute("PRAGMA table_info(images)").fetchall()}
        deleted_expr = "deleted_at" if "deleted_at" in image_columns else "NULL AS deleted_at"
        deleted_where = "WHERE deleted_at IS NULL OR deleted_at = ''" if "deleted_at" in image_columns else ""
        return conn.execute(
            f"SELECT id, user_id, url, thumbnail_url, width, height, created_at, {deleted_expr} FROM images "
            f"{deleted_where} ORDER BY created_at ASC"
        ).fetchall()


def _candidate_from_row(row: Any, *, include_seed: bool) -> dict[str, Any] | None:
    image_id = main._row_get(row, "id")
    rel = _media_rel_from_url(main._row_get(row, "url"))
    if not rel:
        return {"image_id": image_id, "skip_reason": "invalid_url"}
    path = (main.MEDIA / rel).resolve()
    try:
        path.relative_to(main.MEDIA.resolve())
    except ValueError:
        return {"image_id": image_id, "file": rel, "skip_reason": "outside_media"}
    if not path.exists() or not path.is_file():
        return {"image_id": image_id, "file": rel, "skip_reason": "missing_source"}
    try:
        with Image.open(path) as opened:
            width, height = opened.size
            fmt = opened.format or ""
    except Exception as exc:
        return {"image_id": image_id, "file": rel, "skip_reason": f"unreadable_source:{type(exc).__name__}"}
    bucket = gallery_original_audit._source_bucket(row)
    if bucket == "seed" and not include_seed:
        return {"image_id": image_id, "file": rel, "bucket": bucket, "skip_reason": "seed_not_requested"}
    size = path.stat().st_size
    reasons = gallery_original_audit._candidate_reason(path, width, height, size)
    if not reasons:
        return None
    target_rel = _safe_target_rel(rel)
    return {
        "image_id": image_id,
        "user_id": main._row_get(row, "user_id"),
        "source": rel,
        "source_bytes": size,
        "source_human": _bytes_fmt(size),
        "source_width": width,
        "source_height": height,
        "source_format": fmt,
        "target": target_rel,
        "bucket": bucket,
        "reasons": reasons,
    }


def _write_optimized(source_rel: str, target_rel: str) -> dict[str, Any]:
    source = (main.MEDIA / source_rel).resolve()
    target = (main.MEDIA / target_rel).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as opened:
        saved = main.save_gallery_original(opened, target.with_suffix("").relative_to(main.MEDIA).as_posix())
    if saved.resolve() != target:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(saved), str(target))
    with Image.open(target) as optimized:
        width, height = optimized.size
    size = target.stat().st_size
    return {"target_bytes": size, "target_human": _bytes_fmt(size), "target_width": width, "target_height": height}


def migrate_gallery_originals(
    *,
    apply: bool = False,
    include_seed: bool = False,
    delete_source: bool = False,
    item_limit: int = 50,
) -> dict[str, Any]:
    main.init_db()
    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in _active_image_rows():
        candidate = _candidate_from_row(row, include_seed=include_seed)
        if not candidate:
            continue
        if "skip_reason" in candidate:
            skipped.append(candidate)
            continue
        candidates.append(candidate)
    total_candidates = len(candidates)
    candidates = sorted(candidates, key=lambda item: int(item["source_bytes"]), reverse=True)[:item_limit]

    migrated: list[dict[str, Any]] = []
    for item in candidates:
        if apply:
            details = _write_optimized(str(item["source"]), str(item["target"]))
            target_url = main.public_url(main.MEDIA / str(item["target"]), str(item["user_id"]))
            with main.db() as conn:
                row = conn.execute("SELECT thumbnail_url FROM images WHERE id = ?", (item["image_id"],)).fetchone()
                source_rel = str(item["source"])
                thumbnail_url = main._row_get(row, "thumbnail_url") if row else None
                new_thumbnail_url = target_url if _media_rel_from_url(thumbnail_url) == source_rel else thumbnail_url
                conn.execute(
                    "UPDATE images SET url = ?, thumbnail_url = ?, width = ?, height = ? WHERE id = ?",
                    (target_url, new_thumbnail_url, details["target_width"], details["target_height"], item["image_id"]),
                )
            if delete_source:
                try:
                    (main.MEDIA / str(item["source"])).unlink()
                except FileNotFoundError:
                    pass
            migrated.append({**item, **details, "new_url": target_url, "source_deleted": bool(delete_source)})
        else:
            migrated.append(item)

    source_bytes = sum(int(item.get("source_bytes") or 0) for item in migrated)
    target_bytes = sum(int(item.get("target_bytes") or 0) for item in migrated)
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if apply else "dry_run",
        "changes_db": bool(apply),
        "deletes_source": bool(apply and delete_source),
        "include_seed": include_seed,
        "limit": item_limit,
        "summary": {
            "candidates_total_before_limit": total_candidates,
            "items": len(migrated),
            "source_bytes": source_bytes,
            "source_human": _bytes_fmt(source_bytes),
            "target_bytes": target_bytes,
            "target_human": _bytes_fmt(target_bytes) if target_bytes else "not measured",
            "estimated_reclaimable_bytes": source_bytes - target_bytes if target_bytes else 0,
            "estimated_reclaimable_human": _bytes_fmt(source_bytes - target_bytes) if target_bytes else "not measured",
            "skipped": len(skipped),
        },
        "items": migrated,
        "skipped": skipped[:item_limit],
    }


def main_cli() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Plan or apply active gallery original WebP optimization.")
    parser.add_argument("--apply", action="store_true", help="Actually create optimized files and update images.url.")
    parser.add_argument("--include-seed", action="store_true", help="Include seed/demo originals. Default optimizes user originals only.")
    parser.add_argument("--delete-source", action="store_true", help="Delete old source file after successful DB update. Requires --apply.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum candidates to process.")
    parser.add_argument("--report", default="", help="Optional JSON report path.")
    args = parser.parse_args()
    if args.delete_source and not args.apply:
        raise SystemExit("--delete-source requires --apply")
    report = migrate_gallery_originals(
        apply=bool(args.apply),
        include_seed=bool(args.include_seed),
        delete_source=bool(args.delete_source),
        item_limit=max(1, int(args.limit or 50)),
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main_cli()
