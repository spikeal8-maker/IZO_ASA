from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import main
from media_storage_audit import _bytes_fmt, _media_rel_from_url


def _path_exists(rel: str | None) -> bool:
    if not rel:
        return False
    path = (main.MEDIA / rel).resolve()
    try:
        path.relative_to(main.MEDIA.resolve())
    except ValueError:
        return False
    return path.exists()


def _safe_user_label(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "internal_user_id": main._row_get(row, "internal_user_id"),
        "username": main._row_get(row, "username"),
        "display_name": main._row_get(row, "display_name"),
        "first_name": main._row_get(row, "first_name"),
        "role": main._row_get(row, "role"),
        "banned": int(main._row_get(row, "banned") or 0),
    }


def audit_user_gallery_links(*, item_limit: int = 50) -> dict[str, Any]:
    main.init_db()
    report: dict[str, Any] = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "db_path": str(main.DB_PATH),
        "media_dir": str(main.MEDIA),
        "totals": {},
        "issues": [],
        "missing_users": [],
        "system_missing_users": [],
        "users_without_internal_id": [],
        "duplicate_internal_user_ids": [],
        "job_user_mismatches": [],
        "active_missing_files": [],
        "deleted_missing_files": [],
        "per_user": [],
    }

    per_user: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "active_images": 0,
        "deleted_images": 0,
        "missing_originals": 0,
        "missing_thumbnails": 0,
        "bytes_existing": 0,
        "sample_missing": [],
    })
    missing_user_count = 0
    system_missing_user_count = 0
    active_missing_file_count = 0
    deleted_missing_file_count = 0
    job_user_mismatch_count = 0

    with main.db() as conn:
        users = {row["id"]: row for row in conn.execute("SELECT * FROM users").fetchall()}
        internal_counts: dict[str, int] = defaultdict(int)
        for row in users.values():
            iuid = main._row_get(row, "internal_user_id")
            if iuid:
                internal_counts[str(iuid)] += 1
            else:
                report["users_without_internal_id"].append(_safe_user_label(row))
        report["duplicate_internal_user_ids"] = [
            {"internal_user_id": iuid, "count": count}
            for iuid, count in sorted(internal_counts.items())
            if count > 1
        ]

        image_columns = {row["name"] for row in conn.execute("PRAGMA table_info(images)").fetchall()}
        has_deleted_at = "deleted_at" in image_columns
        deleted_expr = "deleted_at" if has_deleted_at else "NULL AS deleted_at"
        image_rows = conn.execute(
            f"""
            SELECT id, user_id, job_id, url, thumbnail_url, width, height, mode, provider, created_at, {deleted_expr}
            FROM images
            ORDER BY created_at DESC
            """
        ).fetchall()
        job_rows = {row["id"]: row for row in conn.execute("SELECT id, user_id, result_image_id, status FROM jobs").fetchall()}

        active_images = 0
        deleted_images = 0
        for image in image_rows:
            user_id = image["user_id"] or ""
            is_deleted = bool(main._row_get(image, "deleted_at"))
            if is_deleted:
                deleted_images += 1
                per_user[user_id]["deleted_images"] += 1
            else:
                active_images += 1
                per_user[user_id]["active_images"] += 1

            if user_id not in users:
                item = {
                    "image_id": image["id"],
                    "user_id": user_id,
                    "job_id": main._row_get(image, "job_id"),
                    "deleted": is_deleted,
                }
                if user_id == "seed_editorial":
                    system_missing_user_count += 1
                    target = report["system_missing_users"]
                else:
                    missing_user_count += 1
                    target = report["missing_users"]
                if len(target) < item_limit:
                    target.append(item)

            job_id = main._row_get(image, "job_id")
            if job_id and job_id in job_rows:
                job_user_id = main._row_get(job_rows[job_id], "user_id")
                if job_user_id and job_user_id != user_id:
                    job_user_mismatch_count += 1
                    if len(report["job_user_mismatches"]) < item_limit:
                        report["job_user_mismatches"].append(
                            {
                                "image_id": image["id"],
                                "image_user_id": user_id,
                                "job_id": job_id,
                                "job_user_id": job_user_id,
                                "job_status": main._row_get(job_rows[job_id], "status"),
                                "deleted": is_deleted,
                            }
                        )

            for field, counter in (("url", "missing_originals"), ("thumbnail_url", "missing_thumbnails")):
                rel = _media_rel_from_url(main._row_get(image, field))
                if rel and _path_exists(rel):
                    path = main.MEDIA / rel
                    per_user[user_id]["bytes_existing"] += path.stat().st_size
                    continue
                per_user[user_id][counter] += 1
                missing = {
                    "image_id": image["id"],
                    "user_id": user_id,
                    "field": field,
                    "file": rel,
                    "deleted": is_deleted,
                }
                if is_deleted:
                    deleted_missing_file_count += 1
                    target = report["deleted_missing_files"]
                else:
                    active_missing_file_count += 1
                    target = report["active_missing_files"]
                if len(target) < item_limit:
                    target.append(missing)
                if len(per_user[user_id]["sample_missing"]) < 5:
                    per_user[user_id]["sample_missing"].append(missing)

        report["totals"] = {
            "users": len(users),
            "images": len(image_rows),
            "active_images": active_images,
            "deleted_images": deleted_images,
            "missing_user_images": missing_user_count,
            "system_missing_user_images": system_missing_user_count,
            "active_missing_file_refs": active_missing_file_count,
            "deleted_missing_file_refs": deleted_missing_file_count,
            "job_user_mismatches": job_user_mismatch_count,
        }
        rows = []
        for user_id, data in per_user.items():
            user = users.get(user_id)
            rows.append(
                {
                    "user": _safe_user_label(user) or {"id": user_id, "missing_user_row": True},
                    "active_images": data["active_images"],
                    "deleted_images": data["deleted_images"],
                    "missing_originals": data["missing_originals"],
                    "missing_thumbnails": data["missing_thumbnails"],
                    "bytes_existing": data["bytes_existing"],
                    "bytes_existing_human": _bytes_fmt(int(data["bytes_existing"])),
                    "sample_missing": data["sample_missing"],
                }
            )
        report["per_user"] = sorted(
            rows,
            key=lambda item: (
                int(item["missing_originals"]) + int(item["missing_thumbnails"]),
                int(item["active_images"]),
            ),
            reverse=True,
        )[:item_limit]

    if report["missing_users"]:
        report["issues"].append("images_with_missing_user")
    if report["users_without_internal_id"]:
        report["issues"].append("users_without_internal_id")
    if report["duplicate_internal_user_ids"]:
        report["issues"].append("duplicate_internal_user_ids")
    if report["job_user_mismatches"]:
        report["issues"].append("job_user_mismatches")
    if report["active_missing_files"]:
        report["issues"].append("active_image_file_refs_missing")
    return report


def main_cli() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Read-only audit for users/images/jobs/gallery links.")
    parser.add_argument("--report", default="", help="Optional JSON report path.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum items per detailed list.")
    parser.add_argument("--fail-on-issues", action="store_true", help="Exit with code 2 if issues are found.")
    args = parser.parse_args()
    report = audit_user_gallery_links(item_limit=max(1, int(args.limit or 50)))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.fail_on_issues and report["issues"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main_cli()
