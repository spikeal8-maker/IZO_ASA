from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pytest

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


class RetryReadCursor(sqlite3.Cursor):
    after_read: Callable[[], None] | None = None

    def fetchone(self) -> sqlite3.Row | None:
        row = super().fetchone()
        callback = self.after_read
        self.after_read = None
        if callback is not None:
            self.close()
            callback()
        return row


class RetryReadConnection(sqlite3.Connection):
    after_retry_read: Callable[[], None] | None = None

    def execute(
        self,
        sql: str,
        parameters: tuple[object, ...] = (),
    ) -> sqlite3.Cursor:
        cursor = self.cursor(factory=RetryReadCursor)
        cursor.execute(sql, parameters)
        if sql.lstrip().startswith("SELECT attempts"):
            cursor.after_read = self.after_retry_read
            self.after_retry_read = None
        return cursor


def enqueue_test_message(conn: sqlite3.Connection) -> str:
    enqueue_payment_notification(
        conn,
        payment_id="pay_terminal",
        internal_user_id="user_terminal",
        event_type="payment_succeeded",
        channel="email",
        destination="nobody@example.invalid",
        payload={"tokens": 100},
        now="2026-07-16T10:00:00+00:00",
    )
    conn.commit()
    return claim_pending_messages(
        conn, now=datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc)
    )[0].id


@pytest.mark.parametrize("callbacks", [("sent", "retry"), ("retry", "sent")])
def test_outbox_success_is_terminal_regardless_of_callback_order(
    callbacks: tuple[str, str],
) -> None:
    with closing(connection()) as conn:
        message_id = enqueue_test_message(conn)
        for callback in callbacks:
            if callback == "sent":
                mark_sent(conn, message_id, sent_at="2026-07-16T10:01:00+00:00")
            else:
                mark_retry(
                    conn,
                    message_id,
                    "delivery failure",
                    now=datetime(2026, 7, 16, 10, 2, tzinfo=timezone.utc),
                )
        row = conn.execute(
            "SELECT * FROM payment_notification_outbox WHERE id=?", (message_id,)
        ).fetchone()
        assert row["status"] == "sent"
        assert row["sent_at"] == "2026-07-16T10:01:00+00:00"
        assert row["last_error"] is None
        assert row["attempts"] == (0 if callbacks[0] == "sent" else 1)
        assert pending_messages(conn, now="2026-07-16T11:00:00+00:00") == []


@pytest.mark.parametrize("callback", ["retry", "sent"])
def test_outbox_sent_row_is_unchanged_by_repeated_callbacks(callback: str) -> None:
    with closing(connection()) as conn:
        message_id = enqueue_test_message(conn)
        mark_sent(conn, message_id, sent_at="2026-07-16T10:01:00+00:00")
        original = dict(conn.execute(
            "SELECT * FROM payment_notification_outbox WHERE id=?", (message_id,)
        ).fetchone())
        if callback == "retry":
            mark_retry(
                conn, message_id, "late failure",
                now=datetime(2026, 7, 16, 10, 2, tzinfo=timezone.utc),
            )
        else:
            mark_sent(conn, message_id, sent_at="2026-07-16T11:01:00+00:00")
        assert dict(conn.execute(
            "SELECT * FROM payment_notification_outbox WHERE id=?", (message_id,)
        ).fetchone()) == original


def test_outbox_sent_commit_between_retry_read_and_update_wins(tmp_path: Path) -> None:
    database = tmp_path / "outbox.sqlite3"
    with (
        closing(sqlite3.connect(database, factory=RetryReadConnection)) as retry_conn,
        closing(sqlite3.connect(database)) as delivery_conn,
    ):
        retry_conn.row_factory = sqlite3.Row
        delivery_conn.row_factory = sqlite3.Row
        ensure_outbox_schema(retry_conn)
        message_id = enqueue_test_message(retry_conn)
        committed_rows = []

        def complete_delivery() -> None:
            mark_sent(delivery_conn, message_id, sent_at="2026-07-16T10:01:00+00:00")
            delivery_conn.commit()
            committed_rows.append(dict(delivery_conn.execute(
                "SELECT * FROM payment_notification_outbox WHERE id=?", (message_id,)
            ).fetchone()))

        retry_conn.after_retry_read = complete_delivery
        mark_retry(
            retry_conn, message_id, "stale delivery failure",
            now=datetime(2026, 7, 16, 10, 2, tzinfo=timezone.utc),
        )
        retry_conn.commit()
        assert len(committed_rows) == 1
        assert dict(delivery_conn.execute(
            "SELECT * FROM payment_notification_outbox WHERE id=?", (message_id,)
        ).fetchone()) == committed_rows[0]
        assert pending_messages(delivery_conn, now="2026-07-16T11:00:00+00:00") == []


def test_outbox_failed_callbacks_preserve_existing_transitions() -> None:
    with closing(connection()) as conn:
        message_id = enqueue_test_message(conn)
        mark_retry(conn, message_id, "first failure", max_attempts=1)
        mark_retry(conn, message_id, "next failure")
        row = conn.execute(
            "SELECT status, attempts FROM payment_notification_outbox WHERE id=?",
            (message_id,),
        ).fetchone()
        assert dict(row) == {"status": "retry", "attempts": 2}
        mark_retry(conn, message_id, "final failure", max_attempts=1)
        mark_sent(conn, message_id, sent_at="2026-07-16T10:05:00+00:00")
        row = conn.execute(
            "SELECT status, attempts, sent_at FROM payment_notification_outbox WHERE id=?",
            (message_id,),
        ).fetchone()
        assert dict(row) == {
            "status": "sent", "attempts": 3, "sent_at": "2026-07-16T10:05:00+00:00",
        }
