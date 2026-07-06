from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

import main


def _bytes_stats(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "avg": 0, "max": 0, "total": 0}
    return {
        "count": len(values),
        "avg": round(mean(values), 2),
        "max": max(values),
        "total": sum(values),
    }


def _feed_path(name: str | None) -> Path | None:
    if not name:
        return None
    path = (main.MEDIA / name).resolve()
    try:
        path.relative_to(main.MEDIA.resolve())
    except ValueError:
        return None
    return path


def audit_feed_media(*, item_limit: int = 50) -> dict[str, Any]:
    main.init_db()
    report: dict[str, Any] = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "db_path": str(main.DB_PATH),
        "media_dir": str(main.MEDIA),
        "statuses": {},
        "ready_publications": 0,
        "seed_ready_publications": 0,
        "media_missing_publications": [],
        "published_not_ready": [],
        "missing_files": [],
        "size_stats": {},
        "orphan_feed_files": [],
        "issues": [],
    }
    seen_feed_names: set[str] = set()
    thumb_bytes: list[int] = []
    large_bytes: list[int] = []
    with main.db() as conn:
        for row in conn.execute("SELECT status, COUNT(*) AS c FROM feed_publications GROUP BY status ORDER BY status"):
            report["statuses"][row["status"]] = int(row["c"] or 0)

        rows = conn.execute(
            """
            SELECT id, status, feed_thumb_name, feed_large_name, feed_thumb_bytes, feed_large_bytes,
                   media_ready_at, media_error, is_seed, author_type, legacy_user_id
            FROM feed_publications
            ORDER BY created_at DESC
            """
        ).fetchall()
        for row in rows:
            pub_id = row["id"]
            is_seed = (
                str(pub_id).startswith("seed-")
                or int(main._row_get(row, "is_seed") or 0) == 1
                or str(main._row_get(row, "author_type") or "") == "seed"
                or str(main._row_get(row, "legacy_user_id") or "") == "seed_editorial"
            )
            if row["status"] == "media_missing":
                report["media_missing_publications"].append(
                    {"id": pub_id, "error": main._row_get(row, "media_error") or ""}
                )
                continue

            if row["status"] != "published":
                continue

            thumb_name = main._row_get(row, "feed_thumb_name")
            large_name = main._row_get(row, "feed_large_name")
            ready = bool(main._row_get(row, "media_ready_at") and thumb_name and large_name)
            if not ready:
                report["published_not_ready"].append(
                    {"id": pub_id, "media_ready_at": main._row_get(row, "media_ready_at"), "thumb": thumb_name, "large": large_name}
                )
                continue

            report["ready_publications"] += 1
            if is_seed:
                report["seed_ready_publications"] += 1

            for kind, name in (("thumb", thumb_name), ("large", large_name)):
                seen_feed_names.add(str(name))
                path = _feed_path(str(name))
                if path is None or not path.exists():
                    report["missing_files"].append({"id": pub_id, "variant": kind, "file": name})
                    continue
                size = path.stat().st_size
                if kind == "thumb":
                    thumb_bytes.append(size)
                else:
                    large_bytes.append(size)

        feed_dir = main.MEDIA / "feed"
        if feed_dir.exists():
            for path in feed_dir.glob("*.webp"):
                rel = path.relative_to(main.MEDIA).as_posix()
                if rel not in seen_feed_names:
                    report["orphan_feed_files"].append({"file": rel, "bytes": path.stat().st_size})

    report["media_missing_publications"] = report["media_missing_publications"][:item_limit]
    report["published_not_ready"] = report["published_not_ready"][:item_limit]
    report["missing_files"] = report["missing_files"][:item_limit]
    report["orphan_feed_files"] = report["orphan_feed_files"][:item_limit]
    report["size_stats"] = {
        "thumb": _bytes_stats(thumb_bytes),
        "large": _bytes_stats(large_bytes),
    }

    if report["published_not_ready"]:
        report["issues"].append("published_not_ready")
    if report["missing_files"]:
        report["issues"].append("missing_files")
    if report["size_stats"]["thumb"]["avg"] > 120_000:
        report["issues"].append("thumb_average_above_target")
    if report["size_stats"]["large"]["avg"] > 450_000:
        report["issues"].append("large_average_above_target")
    return report


def main_cli() -> None:
    parser = argparse.ArgumentParser(description="Read-only audit for public feed media variants.")
    parser.add_argument("--report", default="", help="Optional JSON report path.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum items per issue list.")
    parser.add_argument("--fail-on-issues", action="store_true", help="Exit with code 2 if hard issues are found.")
    args = parser.parse_args()
    report = audit_feed_media(item_limit=max(1, int(args.limit or 50)))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    print(text)
    hard_issues = {"published_not_ready", "missing_files"} & set(report["issues"])
    if args.fail_on_issues and hard_issues:
        raise SystemExit(2)


if __name__ == "__main__":
    main_cli()
