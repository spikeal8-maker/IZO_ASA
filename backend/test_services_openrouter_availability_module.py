from __future__ import annotations

import sqlite3

from app.services.openrouter_availability import (
    attach_to_key_status,
    default_snapshot,
    load_snapshot,
    record_failure,
    record_success,
)


def connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE admin_settings (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    return conn


def test_billing_failure_is_durable_and_overrides_key_health() -> None:
    conn = connection()

    record_failure(conn, 402, now="2026-07-29T10:00:00+00:00")
    snapshot = load_snapshot(conn)
    status = attach_to_key_status({"ok": True, "configured": True}, snapshot)

    assert snapshot["state"] == "billing_blocked"
    assert snapshot["lastStatusCode"] == 402
    assert status["ready"] is False
    assert status["availability"]["lastFailureAt"] == "2026-07-29T10:00:00+00:00"


def test_real_success_clears_previous_billing_block() -> None:
    conn = connection()
    record_failure(conn, 402, now="2026-07-29T10:00:00+00:00")

    record_success(conn, now="2026-07-29T10:05:00+00:00")
    status = attach_to_key_status({"ok": True, "configured": True}, load_snapshot(conn))

    assert status["ready"] is True
    assert status["availability"]["state"] == "available"
    assert status["availability"]["lastSuccessAt"] == "2026-07-29T10:05:00+00:00"


def test_transient_failure_does_not_hide_existing_billing_block() -> None:
    conn = connection()
    record_failure(conn, 402, now="2026-07-29T10:00:00+00:00")

    record_failure(conn, 429, now="2026-07-29T10:01:00+00:00")
    snapshot = load_snapshot(conn)

    assert snapshot["state"] == "billing_blocked"
    assert snapshot["lastStatusCode"] == 429


def test_key_check_without_real_generation_is_unknown_not_available() -> None:
    status = attach_to_key_status({"ok": True, "configured": True}, default_snapshot())

    assert status["ready"] is None
