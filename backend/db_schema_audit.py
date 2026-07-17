from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any

import main


EXPECTED_COLUMNS: dict[str, set[str]] = {
    "feed_publications": {
        "media_type",
        "video_id",
        "feed_thumb_name",
        "feed_large_name",
        "feed_thumb_width",
        "feed_thumb_height",
        "feed_thumb_bytes",
        "feed_large_width",
        "feed_large_height",
        "feed_large_bytes",
        "media_ready_at",
        "media_error",
        "native_aspect_ratio",
        "orientation",
        "source_type",
        "source_label",
        "display_policy",
        "category",
        "remix_policy",
        "tags_json",
        "updated_at",
        "moderation_status",
        "moderation_reason",
        "moderated_at",
        "moderated_by_internal_user_id",
        "source_job_id",
        "metric_origin",
        "video_poster_name",
        "video_poster_width",
        "video_poster_height",
        "video_poster_bytes",
        "video_preview_name",
        "video_preview_bytes",
        "video_full_name",
        "video_full_bytes",
        "duration_ms",
        "has_audio",
    },
    "feed_engagement_events": {
        "id",
        "publication_id",
        "viewer_key",
        "event_type",
        "duration_ms",
        "context_json",
        "created_at",
    },
}

EXPECTED_TABLES = {
    "feed_publications",
    "feed_reactions",
    "feed_author_follows",
    "feed_view_events",
    "feed_engagement_events",
    "feed_subscription_reads",
}

EXPECTED_INDEXES: dict[str, str] = {
    "idx_feed_publications_media_ready": "feed_publications",
    "idx_feed_publications_category_ready_created": "feed_publications",
    "idx_feed_publications_legacy_ready_created": "feed_publications",
    "idx_feed_publications_moderation_created": "feed_publications",
    "idx_feed_publications_media_type_ready_created": "feed_publications",
    "idx_feed_reactions_viewer_kind": "feed_reactions",
    "idx_feed_view_events_viewer_recent": "feed_view_events",
    "idx_feed_view_events_last_viewed": "feed_view_events",
    "idx_feed_engagement_events_type_created": "feed_engagement_events",
    "idx_feed_engagement_events_publication_created": "feed_engagement_events",
    "idx_feed_engagement_events_viewer_created": "feed_engagement_events",
    "idx_images_user_deleted_created": "images",
    "idx_images_job_id": "images",
    "idx_jobs_user_created": "jobs",
    "idx_jobs_result_image": "jobs",
}


def audit_db_schema() -> dict[str, Any]:
    main.init_db()
    report: dict[str, Any] = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "db_path": str(main.DB_PATH),
        "expected_columns": {table: sorted(columns) for table, columns in EXPECTED_COLUMNS.items()},
        "expected_tables": sorted(EXPECTED_TABLES),
        "missing_tables": [],
        "missing_columns": {},
        "expected_indexes": EXPECTED_INDEXES,
        "missing_indexes": [],
        "issues": [],
    }
    with main.db() as conn:
        existing_tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        report["missing_tables"] = sorted(EXPECTED_TABLES - existing_tables)
        report["issues"].extend(f"missing_table:{table}" for table in report["missing_tables"])
        for table, expected in EXPECTED_COLUMNS.items():
            existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            missing = sorted(expected - existing)
            if missing:
                report["missing_columns"][table] = missing
                for column in missing:
                    report["issues"].append(f"missing_column:{table}.{column}")

        rows = conn.execute("SELECT name, tbl_name FROM sqlite_master WHERE type = 'index'").fetchall()
        existing_indexes = {row["name"]: row["tbl_name"] for row in rows}
        for index_name, table in EXPECTED_INDEXES.items():
            if existing_indexes.get(index_name) != table:
                report["missing_indexes"].append(index_name)
                report["issues"].append(f"missing_index:{index_name}")

    return report


def main_cli() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Audit feed/media SQLite schema readiness.")
    parser.add_argument("--fail-on-issues", action="store_true", help="Exit with code 2 if schema issues are found.")
    args = parser.parse_args()
    report = audit_db_schema()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.fail_on_issues and report["issues"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main_cli()
