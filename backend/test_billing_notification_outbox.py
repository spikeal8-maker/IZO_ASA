from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from backend.app.billing.outbox import (
    claim_pending_messages,
    enqueue_payment_notification,
    ensure_outbox_schema,
    mark_retry,
    mark_sent,
    pending_messages,
)


def connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_outbox_schema(conn)
    return conn


def test_outbox_is_idempotent_per_payment_event_and_channel() -> None:
    conn = connection()
    args = {
        "payment_id": "pay_1",
        "internal_user_id": "user_1",
        "event_type": "payment_succeeded",
        "channel": "email",
        "destination": "user@example.com",
        "payload": {"amount": 250},
        "now": "2026-07-16T10:00:00+00:00",
    }
    assert enqueue_payment_notification(conn, **args) is True
    assert enqueue_payment_notification(conn, **args) is False
    assert len(pending_messages(conn, now="2026-07-16T10:00:00+00:00")) == 1


def test_outbox_retries_then_stops_after_limit() -> None:
    conn = connection()
    enqueue_payment_notification(
        conn,
        payment_id="pay_2",
        internal_user_id="user_2",
        event_type="payment_succeeded",
        channel="email",
        destination="user@example.com",
        payload={},
        now="2026-07-16T10:00:00+00:00",
    )
    message = pending_messages(conn, now="2026-07-16T10:00:00+00:00")[0]
    for attempt in range(5):
        mark_retry(
            conn,
            message.id,
            "smtp unavailable",
            now=datetime(2026, 7, 16, 10, attempt, tzinfo=timezone.utc),
        )
    row = conn.execute(
        "SELECT status, attempts, last_error FROM payment_notification_outbox WHERE id=?",
        (message.id,),
    ).fetchone()
    assert dict(row) == {"status": "failed", "attempts": 5, "last_error": "smtp unavailable"}


def test_outbox_marks_delivery_once() -> None:
    conn = connection()
    enqueue_payment_notification(
        conn,
        payment_id="pay_3",
        internal_user_id="user_3",
        event_type="payment_succeeded",
        channel="in_app",
        destination=None,
        payload={"tokens": 100},
        now="2026-07-16T10:00:00+00:00",
    )
    message = pending_messages(conn, now="2026-07-16T10:00:00+00:00")[0]
    mark_sent(conn, message.id, sent_at="2026-07-16T10:01:00+00:00")
    assert pending_messages(conn, now="2026-07-16T11:00:00+00:00") == []


def test_outbox_claim_prevents_duplicate_processing_and_recovers_expired_lease() -> None:
    conn = connection()
    enqueue_payment_notification(
        conn,
        payment_id="pay_4",
        internal_user_id="user_4",
        event_type="payment_succeeded",
        channel="email",
        destination="user@example.com",
        payload={},
        now="2026-07-16T10:00:00+00:00",
    )
    conn.commit()
    first = claim_pending_messages(
        conn,
        now=datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc),
        lease_minutes=5,
    )
    assert len(first) == 1
    assert claim_pending_messages(
        conn,
        now=datetime(2026, 7, 16, 10, 1, tzinfo=timezone.utc),
    ) == []
    recovered = claim_pending_messages(
        conn,
        now=datetime(2026, 7, 16, 10, 6, tzinfo=timezone.utc),
    )
    assert [message.id for message in recovered] == [first[0].id]
