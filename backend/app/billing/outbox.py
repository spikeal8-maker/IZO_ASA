from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


OUTBOX_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS payment_notification_outbox (
    id TEXT PRIMARY KEY,
    payment_id TEXT NOT NULL,
    internal_user_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    channel TEXT NOT NULL,
    destination TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    last_error TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    UNIQUE(payment_id, event_type, channel)
);
CREATE INDEX IF NOT EXISTS idx_payment_notification_outbox_pending
    ON payment_notification_outbox(status, next_attempt_at, created_at);
"""


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    id: str
    payment_id: str
    internal_user_id: str
    event_type: str
    channel: str
    destination: str | None
    attempts: int
    payload: dict[str, Any]


def ensure_outbox_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(OUTBOX_SCHEMA_SQL)


def enqueue_payment_notification(
    conn: sqlite3.Connection,
    *,
    payment_id: str,
    internal_user_id: str,
    event_type: str,
    channel: str,
    destination: str | None,
    payload: Mapping[str, Any],
    now: str | None = None,
) -> bool:
    created_at = now or datetime.now(timezone.utc).isoformat()
    before = conn.total_changes
    conn.execute(
        """
        INSERT OR IGNORE INTO payment_notification_outbox (
            id, payment_id, internal_user_id, event_type, channel, destination,
            status, attempts, next_attempt_at, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            payment_id,
            internal_user_id,
            event_type,
            channel,
            destination,
            created_at,
            json.dumps(dict(payload), ensure_ascii=False),
            created_at,
        ),
    )
    return conn.total_changes > before


def pending_messages(
    conn: sqlite3.Connection,
    *,
    now: str | None = None,
    limit: int = 20,
) -> list[OutboxMessage]:
    current = now or datetime.now(timezone.utc).isoformat()
    rows = conn.execute(
        """
        SELECT * FROM payment_notification_outbox
        WHERE status IN ('pending', 'retry') AND next_attempt_at <= ?
        ORDER BY created_at, id LIMIT ?
        """,
        (current, max(1, min(limit, 100))),
    ).fetchall()
    return [
        OutboxMessage(
            id=row["id"],
            payment_id=row["payment_id"],
            internal_user_id=row["internal_user_id"],
            event_type=row["event_type"],
            channel=row["channel"],
            destination=row["destination"],
            attempts=int(row["attempts"] or 0),
            payload=json.loads(row["payload_json"] or "{}"),
        )
        for row in rows
    ]


def claim_pending_messages(
    conn: sqlite3.Connection,
    *,
    now: datetime | None = None,
    limit: int = 20,
    lease_minutes: int = 5,
) -> list[OutboxMessage]:
    current = now or datetime.now(timezone.utc)
    current_iso = current.isoformat()
    conn.execute("BEGIN IMMEDIATE")
    rows = conn.execute(
        """
        SELECT * FROM payment_notification_outbox
        WHERE (
            status IN ('pending', 'retry')
            OR (status = 'processing' AND next_attempt_at <= ?)
        ) AND next_attempt_at <= ?
        ORDER BY created_at, id LIMIT ?
        """,
        (current_iso, current_iso, max(1, min(limit, 100))),
    ).fetchall()
    if rows:
        ids = [str(row["id"]) for row in rows]
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"UPDATE payment_notification_outbox SET status='processing', next_attempt_at=? "
            f"WHERE id IN ({placeholders})",
            ((current + timedelta(minutes=max(1, lease_minutes))).isoformat(), *ids),
        )
    conn.commit()
    return [
        OutboxMessage(
            id=row["id"],
            payment_id=row["payment_id"],
            internal_user_id=row["internal_user_id"],
            event_type=row["event_type"],
            channel=row["channel"],
            destination=row["destination"],
            attempts=int(row["attempts"] or 0),
            payload=json.loads(row["payload_json"] or "{}"),
        )
        for row in rows
    ]


def mark_sent(conn: sqlite3.Connection, message_id: str, *, sent_at: str | None = None) -> None:
    now = sent_at or datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE payment_notification_outbox SET status='sent', sent_at=?, last_error=NULL WHERE id=?",
        (now, message_id),
    )


def mark_retry(
    conn: sqlite3.Connection,
    message_id: str,
    error: str,
    *,
    now: datetime | None = None,
    max_attempts: int = 5,
) -> None:
    row = conn.execute(
        "SELECT attempts FROM payment_notification_outbox WHERE id=?",
        (message_id,),
    ).fetchone()
    if row is None:
        return
    attempts = int(row["attempts"] or 0) + 1
    current = now or datetime.now(timezone.utc)
    status = "failed" if attempts >= max_attempts else "retry"
    delay_minutes = min(60, 2 ** max(0, attempts - 1))
    conn.execute(
        """
        UPDATE payment_notification_outbox
        SET status=?, attempts=?, next_attempt_at=?, last_error=?
        WHERE id=?
        """,
        (
            status,
            attempts,
            (current + timedelta(minutes=delay_minutes)).isoformat(),
            error[:500],
            message_id,
        ),
    )
