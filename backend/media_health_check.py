from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import feed_media_audit
import media_cleanup_plan
import media_storage_audit
import user_gallery_link_audit

FEED_HARD_ISSUES = {"published_not_ready", "published_missing_sources", "published_deleted_sources", "missing_files"}


def run_media_health_check(*, item_limit: int = 50) -> dict[str, Any]:
    feed = feed_media_audit.audit_feed_media(item_limit=item_limit)
    storage = media_storage_audit.audit_media_storage(item_limit=item_limit)
    users = user_gallery_link_audit.audit_user_gallery_links(item_limit=item_limit)
    cleanup = media_cleanup_plan.build_cleanup_plan(item_limit=item_limit)

    issues: list[str] = []
    for issue in feed.get("issues", []):
        if issue in FEED_HARD_ISSUES:
            issues.append(f"feed:{issue}")
    for prefix, report in (
        ("storage", storage),
        ("users", users),
    ):
        for issue in report.get("issues", []):
            issues.append(f"{prefix}:{issue}")
    for issue in cleanup.get("source_audit", {}).get("issues", []):
        issues.append(f"cleanup_source:{issue}")

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": "ok" if not issues else "issues",
        "issues": issues,
        "summary": {
            "feed": {
                "statuses": feed.get("statuses", {}),
                "ready_publications": feed.get("ready_publications"),
                "seed_ready_publications": feed.get("seed_ready_publications"),
            },
            "storage": {
                "total": storage.get("total"),
                "active_referenced": storage.get("active_referenced"),
                "unreferenced": storage.get("unreferenced"),
            },
            "users": users.get("totals", {}),
            "cleanup": cleanup.get("candidate_summary", {}),
        },
        "reports": {
            "feed": feed,
            "storage": storage,
            "users": users,
            "cleanup": cleanup,
        },
    }


def main_cli() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Run combined feed/media/user health checks.")
    parser.add_argument("--report", default="", help="Optional JSON report path.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum detailed items per nested report.")
    parser.add_argument("--fail-on-issues", action="store_true", help="Exit with code 2 if any issue is found.")
    args = parser.parse_args()
    report = run_media_health_check(item_limit=max(1, int(args.limit or 50)))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.fail_on_issues and report["issues"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main_cli()
