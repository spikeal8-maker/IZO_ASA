from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

import main
from media_storage_audit import _bytes_fmt, _media_rel_from_url

MAX_RECOMMENDED_BYTES = 1_500_000


def _summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    total = sum(int(item.get("bytes") or 0) for item in items)
    return {"count": len(items), "bytes": total, "human": _bytes_fmt(total)}


def _source_bucket(row: Any) -> str:
    user_id = str(main._row_get(row, "user_id") or "")
    rel = _media_rel_from_url(main._row_get(row, "url")) or ""
    if user_id == "seed_editorial" or Path(rel).name.startswith("seed_izo_"):
        return "seed"
    return "user"


def _candidate_reason(path: Path, width: int, height: int, size: int) -> list[str]:
    reasons: list[str] = []
    if path.suffix.lower() != ".webp":
        reasons.append("legacy_format")
    if max(width, height) > main.GALLERY_IMAGE_MAX_SIDE:
        reasons.append("oversized_dimensions")
    if size > MAX_RECOMMENDED_BYTES:
        reasons.append("oversized_bytes")
    return reasons


def audit_gallery_originals(*, item_limit: int = 50) -> dict[str, Any]:
    main.init_db()
    report: dict[str, Any] = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "db_path": str(main.DB_PATH),
        "media_dir": str(main.MEDIA),
        "policy": {
            "format": "webp",
            "max_side": main.GALLERY_IMAGE_MAX_SIDE,
            "quality": main.GALLERY_IMAGE_WEBP_QUALITY,
            "recommended_max_bytes": MAX_RECOMMENDED_BYTES,
            "recommended_max_bytes_human": _bytes_fmt(MAX_RECOMMENDED_BYTES),
        },
        "totals": {},
        "by_bucket": {},
        "candidates": [],
        "missing_files": [],
        "unreadable_files": [],
        "issues": [],
    }
    rows: list[Any] = []
    with main.db() as conn:
        image_columns = {row["name"] for row in conn.execute("PRAGMA table_info(images)").fetchall()}
        deleted_expr = "deleted_at" if "deleted_at" in image_columns else "NULL AS deleted_at"
        deleted_where = "WHERE deleted_at IS NULL OR deleted_at = ''" if "deleted_at" in image_columns else ""
        rows = conn.execute(
            f"SELECT id, user_id, url, width, height, created_at, {deleted_expr} FROM images "
            f"{deleted_where}"
        ).fetchall()

    checked: list[dict[str, Any]] = []
    for row in rows:
        image_id = main._row_get(row, "id")
        rel = _media_rel_from_url(main._row_get(row, "url"))
        if not rel:
            report["missing_files"].append({"image_id": image_id, "file": None, "reason": "invalid_url"})
            continue
        path = (main.MEDIA / rel).resolve()
        try:
            path.relative_to(main.MEDIA.resolve())
        except ValueError:
            report["missing_files"].append({"image_id": image_id, "file": rel, "reason": "outside_media"})
            continue
        if not path.exists():
            report["missing_files"].append({"image_id": image_id, "file": rel, "reason": "missing"})
            continue
        size = path.stat().st_size
        try:
            with Image.open(path) as opened:
                width, height = opened.size
                fmt = opened.format or ""
        except Exception as exc:
            report["unreadable_files"].append({"image_id": image_id, "file": rel, "error": type(exc).__name__})
            continue
        item = {
            "image_id": image_id,
            "user_id": main._row_get(row, "user_id"),
            "file": rel,
            "bytes": size,
            "human": _bytes_fmt(size),
            "width": width,
            "height": height,
            "format": fmt,
            "bucket": _source_bucket(row),
            "reasons": _candidate_reason(path, width, height, size),
        }
        checked.append(item)
        if item["reasons"]:
            report["candidates"].append(item)

    report["totals"] = {
        "active_originals": len(rows),
        "checked": len(checked),
        "candidates": len(report["candidates"]),
        "missing_files": len(report["missing_files"]),
        "unreadable_files": len(report["unreadable_files"]),
    }
    for bucket in ("user", "seed"):
        bucket_items = [item for item in checked if item["bucket"] == bucket]
        bucket_candidates = [item for item in report["candidates"] if item["bucket"] == bucket]
        report["by_bucket"][bucket] = {
            "checked": _summary(bucket_items),
            "candidates": _summary(bucket_candidates),
        }
    report["candidates"] = sorted(report["candidates"], key=lambda item: int(item["bytes"]), reverse=True)[:item_limit]
    report["missing_files"] = report["missing_files"][:item_limit]
    report["unreadable_files"] = report["unreadable_files"][:item_limit]
    if report["missing_files"]:
        report["issues"].append("missing_files")
    if report["unreadable_files"]:
        report["issues"].append("unreadable_files")
    return report


def main_cli() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Read-only audit for active gallery original optimization candidates.")
    parser.add_argument("--report", default="", help="Optional JSON report path.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum candidates per detailed list.")
    parser.add_argument("--fail-on-issues", action="store_true", help="Exit with code 2 if files are missing/unreadable.")
    args = parser.parse_args()
    report = audit_gallery_originals(item_limit=max(1, int(args.limit or 50)))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.fail_on_issues and report["issues"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main_cli()
