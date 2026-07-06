from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import main


def _bytes_fmt(value: int) -> str:
    if value >= 1024 * 1024 * 1024:
        return f"{value / (1024 * 1024 * 1024):.2f} GB"
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.2f} MB"
    if value >= 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value} B"


def _media_rel_from_url(url: str | None) -> str | None:
    name = main._feed_media_name(url)
    if not name:
        return None
    rel = Path(name.replace("\\", "/")).as_posix()
    if rel.startswith("../") or rel == ".." or "/../" in rel:
        return None
    return rel


def _add_ref(refs: dict[str, set[str]], rel: str | None, source: str) -> None:
    if not rel:
        return
    refs.setdefault(rel, set()).add(source)


def _file_kind(rel: str) -> str:
    name = Path(rel).name
    if rel.startswith("feed/"):
        return "feed_variant"
    if name.endswith("_thumb.webp"):
        return "gallery_thumb"
    if name.startswith("seed_izo_"):
        return "seed_original"
    return "original_or_input"


def _summarize_files(items: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: int(item.get("bytes") or 0), reverse=True)[:limit]


def _summary(count: int, bytes_total: int) -> dict[str, Any]:
    return {"count": count, "bytes": bytes_total, "human": _bytes_fmt(bytes_total)}


def audit_media_storage(*, item_limit: int = 50) -> dict[str, Any]:
    main.init_db()
    active_refs: dict[str, set[str]] = {}
    deleted_refs: dict[str, set[str]] = {}
    feed_refs: dict[str, set[str]] = {}

    with main.db() as conn:
        image_columns = {row["name"] for row in conn.execute("PRAGMA table_info(images)").fetchall()}
        has_deleted_at = "deleted_at" in image_columns
        deleted_expr = "deleted_at" if has_deleted_at else "NULL AS deleted_at"
        rows = conn.execute(
            f"SELECT id, url, thumbnail_url, {deleted_expr} FROM images"
        ).fetchall()
        for row in rows:
            target = deleted_refs if main._row_get(row, "deleted_at") else active_refs
            _add_ref(target, _media_rel_from_url(row["url"]), f"images.url:{row['id']}")
            _add_ref(target, _media_rel_from_url(row["thumbnail_url"]), f"images.thumbnail_url:{row['id']}")

        feed_columns = {row["name"] for row in conn.execute("PRAGMA table_info(feed_publications)").fetchall()}
        if {"feed_thumb_name", "feed_large_name"} <= feed_columns:
            for row in conn.execute("SELECT id, feed_thumb_name, feed_large_name FROM feed_publications").fetchall():
                _add_ref(feed_refs, main._row_get(row, "feed_thumb_name"), f"feed.thumb:{row['id']}")
                _add_ref(feed_refs, main._row_get(row, "feed_large_name"), f"feed.large:{row['id']}")

    all_active_refs = set(active_refs) | set(feed_refs)
    all_deleted_refs = set(deleted_refs)
    all_db_refs = all_active_refs | all_deleted_refs

    files: list[dict[str, Any]] = []
    for path in main.MEDIA.rglob("*") if main.MEDIA.exists() else []:
        if not path.is_file():
            continue
        rel = path.relative_to(main.MEDIA).as_posix()
        size = path.stat().st_size
        files.append({"file": rel, "bytes": size, "human": _bytes_fmt(size), "kind": _file_kind(rel)})

    total_bytes = sum(int(item["bytes"]) for item in files)
    active_bytes = 0
    deleted_residue: list[dict[str, Any]] = []
    unreferenced: list[dict[str, Any]] = []
    missing_active_refs: list[dict[str, Any]] = []
    by_kind: dict[str, dict[str, int]] = {}
    existing = {str(item["file"]) for item in files}

    for item in files:
        rel = str(item["file"])
        kind = str(item["kind"])
        bucket = by_kind.setdefault(kind, {"count": 0, "bytes": 0})
        bucket["count"] += 1
        bucket["bytes"] += int(item["bytes"])
        if rel in all_active_refs:
            active_bytes += int(item["bytes"])
        elif rel in all_deleted_refs:
            deleted_residue.append(item)
        elif rel not in all_db_refs:
            unreferenced.append(item)

    for rel in sorted(all_active_refs - existing):
        missing_active_refs.append({"file": rel, "sources": sorted(active_refs.get(rel, set()) | feed_refs.get(rel, set()))})

    report: dict[str, Any] = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "db_path": str(main.DB_PATH),
        "media_dir": str(main.MEDIA),
        "total": _summary(len(files), total_bytes),
        "active_referenced": _summary(len(existing & all_active_refs), active_bytes),
        "deleted_image_residue": _summary(len(deleted_residue), sum(int(item["bytes"]) for item in deleted_residue)),
        "unreferenced": _summary(len(unreferenced), sum(int(item["bytes"]) for item in unreferenced)),
        "by_kind": {kind: _summary(data["count"], data["bytes"]) for kind, data in sorted(by_kind.items())},
        "missing_active_refs": missing_active_refs[:item_limit],
        "largest_deleted_image_residue": _summarize_files(deleted_residue, limit=item_limit),
        "largest_unreferenced": _summarize_files(unreferenced, limit=item_limit),
        "issues": [],
    }
    if missing_active_refs:
        report["issues"].append("missing_active_refs")
    return report


def main_cli() -> None:
    parser = argparse.ArgumentParser(description="Read-only storage audit for backend/media.")
    parser.add_argument("--report", default="", help="Optional JSON report path.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum files per detailed list.")
    parser.add_argument("--fail-on-issues", action="store_true", help="Exit with code 2 if hard issues are found.")
    args = parser.parse_args()
    report = audit_media_storage(item_limit=max(1, int(args.limit or 50)))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.fail_on_issues and report["issues"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main_cli()
