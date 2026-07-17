from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import main


def _video_path(filename: str) -> Path | None:
    if not filename:
        return None
    path = (main.MEDIA / filename).resolve()
    try:
        path.relative_to(main.MEDIA.resolve())
    except ValueError:
        return None
    return path


def audit_video_storage(*, item_limit: int = 50) -> dict[str, Any]:
    """Check private gallery video rows, tariff usage and files after schema setup."""
    main.init_db()
    limit = max(1, int(item_limit or 1))
    report: dict[str, Any] = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "db_path": str(main.DB_PATH),
        "media_dir": str(main.MEDIA),
        "totals": {
            "active": 0,
            "favorite": 0,
            "stored_bytes": 0,
            "file_bytes": 0,
            "pending_deletions": 0,
        },
        "missing_files": [],
        "invalid_paths": [],
        "size_mismatches": [],
        "unindexed_job_files": [],
        "orphan_files": [],
        "failed_deletions": [],
        "over_limit_users": [],
        "issues": [],
        "warnings": [],
    }
    referenced_names: set[str] = set()
    queued_names: set[str] = set()
    with main.db() as conn:
        tariffs = main.get_tariff_config(conn)
        rows = conn.execute(
            "SELECT v.*,j.settings_json AS job_settings,u.plan AS user_plan "
            "FROM videos v LEFT JOIN jobs j ON j.id=v.job_id "
            "LEFT JOIN users u ON u.id=v.user_id "
            "WHERE v.deleted_at IS NULL ORDER BY v.created_at DESC,v.id DESC"
        ).fetchall()
        report["totals"]["active"] = len(rows)
        for row in rows:
            report["totals"]["favorite"] += int(row["is_favorite"] or 0)
            report["totals"]["stored_bytes"] += int(row["stored_bytes"] or 0)
            settings = main.safe_json_load(row["job_settings"]) or {}
            filename = str(settings.get("localFile") or "") if isinstance(settings, dict) else ""
            path = _video_path(filename)
            if not filename or path is None:
                report["invalid_paths"].append({"video_id": row["id"], "job_id": row["job_id"], "file": filename})
                continue
            referenced_names.add(filename)
            if not path.is_file():
                report["missing_files"].append({"video_id": row["id"], "job_id": row["job_id"], "file": filename})
                continue
            actual_bytes = path.stat().st_size
            report["totals"]["file_bytes"] += actual_bytes
            expected_bytes = int(row["stored_bytes"] or 0)
            if expected_bytes != actual_bytes:
                report["size_mismatches"].append(
                    {"video_id": row["id"], "file": filename, "database_bytes": expected_bytes, "file_bytes": actual_bytes}
                )

        job_rows = conn.execute(
            "SELECT j.id,j.user_id,j.settings_json FROM jobs j "
            "LEFT JOIN videos v ON v.job_id=j.id AND v.deleted_at IS NULL "
            "WHERE j.status='completed' AND j.mode IN ('text_to_video','image_to_video','first_last_frame','reference_to_video') "
            "AND v.id IS NULL"
        ).fetchall()
        for row in job_rows:
            settings = main.safe_json_load(row["settings_json"]) or {}
            filename = str(settings.get("localFile") or "") if isinstance(settings, dict) else ""
            path = _video_path(filename)
            if filename and path is not None and path.is_file() and not bool(settings.get("galleryDeleted")):
                referenced_names.add(filename)
                report["unindexed_job_files"].append({"job_id": row["id"], "user_id": row["user_id"], "file": filename})

        deletion_rows = conn.execute(
            "SELECT id,video_id,job_id,filename,attempts,last_error,created_at "
            "FROM video_file_deletions ORDER BY created_at ASC,id ASC"
        ).fetchall()
        report["totals"]["pending_deletions"] = len(deletion_rows)
        for row in deletion_rows:
            queued_names.add(str(row["filename"] or ""))
            if int(row["attempts"] or 0) > 0:
                report["failed_deletions"].append(dict(row))

        usage_rows = conn.execute(
            "SELECT v.user_id,COALESCE(u.plan,'free') AS plan,COUNT(*) AS active,"
            "SUM(CASE WHEN v.is_favorite=1 THEN 1 ELSE 0 END) AS favorite "
            "FROM videos v LEFT JOIN users u ON u.id=v.user_id "
            "WHERE v.deleted_at IS NULL GROUP BY v.user_id,u.plan"
        ).fetchall()
        for row in usage_rows:
            plan = str(row["plan"] or "free").lower()
            if plan not in main.PLAN_ORDER:
                plan = "free"
            storage_limit = int(tariffs[plan]["video_slots"] or 0)
            active = int(row["active"] or 0)
            if active > storage_limit:
                report["over_limit_users"].append(
                    {
                        "user_id": row["user_id"],
                        "plan": plan,
                        "active": active,
                        "favorite": int(row["favorite"] or 0),
                        "limit": storage_limit,
                    }
                )

    if main.MEDIA.exists():
        for path in main.MEDIA.glob("*.mp4"):
            if path.name not in referenced_names and path.name not in queued_names:
                report["orphan_files"].append({"file": path.name, "bytes": path.stat().st_size})

    for key in (
        "missing_files",
        "invalid_paths",
        "size_mismatches",
        "unindexed_job_files",
        "orphan_files",
        "failed_deletions",
        "over_limit_users",
    ):
        report[key] = report[key][:limit]
    for key in ("missing_files", "invalid_paths", "size_mismatches", "unindexed_job_files", "orphan_files", "failed_deletions"):
        if report[key]:
            report["issues"].append(key)
    if report["over_limit_users"]:
        report["warnings"].append("over_limit_users_shrink_on_next_successful_generation")
    return report


def main_cli() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Audit private gallery video rows, quotas and files.")
    parser.add_argument("--report", default="", help="Optional JSON report path.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum detailed items per list.")
    parser.add_argument("--fail-on-issues", action="store_true", help="Exit with code 2 when hard issues are found.")
    args = parser.parse_args()
    report = audit_video_storage(item_limit=max(1, int(args.limit or 50)))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.fail_on_issues and report["issues"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main_cli()
