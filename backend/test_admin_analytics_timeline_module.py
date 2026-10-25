"""Contract tests for the read-only CRM dashboard timeline extraction."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from app.services import admin_analytics as legacy
from app.services import admin_analytics_timeline as timeline


def test_legacy_timeline_imports_are_exact_service_aliases() -> None:
    for symbol in (
        "MOSCOW",
        "IMAGE_JOB_MODES",
        "VIDEO_JOB_MODES",
        "_parse_utc",
        "_generation_kind",
        "_time_buckets",
        "dashboard_generation_timeline",
        "dashboard_presence_timeline",
        "dashboard_payment_timeline",
        "dashboard_payment_summary",
    ):
        assert getattr(legacy, symbol) is getattr(timeline, symbol)


def test_isolated_timeline_results_keep_daily_rolling_and_status_contracts() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE jobs (created_at TEXT, mode TEXT, provider TEXT)")
    connection.execute(
        "CREATE TABLE user_presence_samples (bucket_at TEXT, internal_user_id TEXT, user_id TEXT)"
    )
    connection.execute(
        "CREATE TABLE payments (status TEXT, paid_at TEXT, created_at TEXT, amount INTEGER)"
    )
    now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    timestamp = (now - timedelta(minutes=1)).isoformat()
    connection.executemany(
        "INSERT INTO jobs (created_at,mode,provider) VALUES (?,?,?)",
        [
            (timestamp, "text_to_image", "comfyui"),
            (timestamp, "text_to_image", "openrouter"),
            (timestamp, "text_to_video", "openrouter"),
        ],
    )
    connection.execute(
        "INSERT INTO user_presence_samples (bucket_at,internal_user_id,user_id) VALUES (?,?,?)",
        (timestamp, "verified-user", "legacy-user"),
    )
    connection.executemany(
        "INSERT INTO payments (status,paid_at,created_at,amount) VALUES (?,?,?,?)",
        [
            ("paid", timestamp, timestamp, 120),
            ("failed", timestamp, timestamp, 40),
        ],
    )
    try:
        generated = legacy.dashboard_generation_timeline(connection, days=2, now=now)
        for category in ("local_images", "paid_images", "videos"):
            assert generated[category][-1]["value"] == 1
            assert sum(point["value"] for point in generated[f"{category}_1h"]) == 1
        active = legacy.dashboard_presence_timeline(connection, days=2, now=now)
        assert active["active_users"][-1]["value"] == 1
        assert sum(point["value"] for point in active["active_users_1h"]) == 1
        payments = legacy.dashboard_payment_timeline(connection, days=2, now=now)
        assert payments["payments_paid"][-1]["value"] == 1
        assert payments["payments_failed"][-1]["value"] == 1
        assert legacy.dashboard_payment_summary(connection) == {
            "total_attempts": 2,
            "paid_count": 1,
            "failed_count": 1,
            "revenue_rub": 120,
        }
    finally:
        connection.close()
