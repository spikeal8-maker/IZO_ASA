"""Durable delivery outbox for administrator notifications.

The SQLite row is the source of truth.  The in-process worker only wakes up and
claims due rows; a restart leaves pending and leased work recoverable.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable


SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
DELIVERY_CHANNELS = {"telegram", "email"}


@dataclass(frozen=True, slots=True)
class AdminDelivery:
    id: str
    notification_id: str
    channel: str
    destination: str
    attempts: int
    payload: dict[str, Any]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


def _saved_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    if not _table_exists(conn, "admin_settings"):
        return {}
    row = conn.execute(
        "SELECT value_json FROM admin_settings "
        "WHERE key = 'admin_notification_settings'"
    ).fetchone()
    if row is None:
        return {}
    raw = row["value_json"] if isinstance(row, sqlite3.Row) else row[0]
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def enqueue_configured_admin_deliveries(
    conn: sqlite3.Connection,
    *,
    notification_id: str,
    category: str,
    severity: str,
    title: str,
    message: str,
    action_url: str | None,
    created_at: str,
) -> int:
    """Persist configured channel obligations in the notification transaction."""

    if not _table_exists(conn, "admin_notification_delivery_outbox"):
        return 0
    settings = _saved_settings(conn)
    minimum = str(settings.get("minimumSeverity") or "info")
    if SEVERITY_RANK.get(severity, -1) < SEVERITY_RANK.get(minimum, 0):
        return 0
    categories = settings.get("categories")
    if isinstance(categories, dict) and categories.get(category) is False:
        return 0

    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        created = _utc_now()
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    delivery_mode = str(settings.get("digestMode") or "immediate")
    next_attempt = (
        created + timedelta(days=1) if delivery_mode == "daily" else created
    ).isoformat()
    payload = json.dumps(
        {
            "title": title,
            "message": message,
            "actionUrl": action_url,
            "category": category,
            "severity": severity,
            "deliveryMode": delivery_mode,
        },
        ensure_ascii=False,
    )
    destinations = []
    if settings.get("telegramEnabled") and str(
        settings.get("telegramChatId") or ""
    ).strip():
        destinations.append(
            ("telegram", str(settings["telegramChatId"]).strip())
        )
    if settings.get("emailEnabled") and str(
        settings.get("emailAddress") or ""
    ).strip():
        destinations.append(("email", str(settings["emailAddress"]).strip()))

    inserted = 0
    for channel, destination in destinations:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO admin_notification_delivery_outbox
                (id, notification_id, channel, destination, status, attempts,
                 next_attempt_at, payload_json, created_at)
            VALUES (?, ?, ?, ?, 'pending', 0, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                notification_id,
                channel,
                destination,
                next_attempt,
                payload,
                created.isoformat(),
            ),
        )
        inserted += cursor.rowcount
    return inserted


def _delivery_from_row(row: sqlite3.Row) -> AdminDelivery:
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except json.JSONDecodeError:
        payload = {}
    return AdminDelivery(
        id=str(row["id"]),
        notification_id=str(row["notification_id"]),
        channel=str(row["channel"]),
        destination=str(row["destination"]),
        attempts=int(row["attempts"] or 0),
        payload=payload if isinstance(payload, dict) else {},
    )


def claim_pending_deliveries(
    conn: sqlite3.Connection,
    *,
    now: datetime | None = None,
    limit: int = 20,
    lease_seconds: int = 120,
) -> list[AdminDelivery]:
    current = now or _utc_now()
    current_iso = current.isoformat()
    conn.execute("BEGIN IMMEDIATE")
    rows = conn.execute(
        """
        SELECT * FROM admin_notification_delivery_outbox
        WHERE (
            status IN ('pending', 'retry')
            OR (status = 'processing' AND next_attempt_at <= ?)
        ) AND next_attempt_at <= ?
        ORDER BY created_at, id
        LIMIT ?
        """,
        (current_iso, current_iso, max(1, min(int(limit), 100))),
    ).fetchall()
    if rows:
        ids = [str(row["id"]) for row in rows]
        placeholders = ",".join("?" for _ in ids)
        lease_until = (
            current + timedelta(seconds=max(30, int(lease_seconds)))
        ).isoformat()
        conn.execute(
            f"UPDATE admin_notification_delivery_outbox "
            f"SET status='processing', next_attempt_at=? "
            f"WHERE id IN ({placeholders})",
            (lease_until, *ids),
        )
    conn.commit()
    return [_delivery_from_row(row) for row in rows]


def mark_delivery_sent(
    conn: sqlite3.Connection,
    delivery_id: str,
    *,
    external_id: str | None = None,
    sent_at: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE admin_notification_delivery_outbox
        SET status='sent', external_id=?, sent_at=?, last_error=NULL
        WHERE id=?
        """,
        (external_id, sent_at or _utc_now().isoformat(), delivery_id),
    )


def mark_delivery_retry(
    conn: sqlite3.Connection,
    delivery_id: str,
    error: str,
    *,
    now: datetime | None = None,
    max_attempts: int = 5,
) -> None:
    row = conn.execute(
        "SELECT attempts FROM admin_notification_delivery_outbox WHERE id=?",
        (delivery_id,),
    ).fetchone()
    if row is None:
        return
    attempts = int(row["attempts"] or 0) + 1
    current = now or _utc_now()
    status = "failed" if attempts >= max(1, int(max_attempts)) else "retry"
    delay = min(3600, 60 * (2 ** max(0, attempts - 1)))
    conn.execute(
        """
        UPDATE admin_notification_delivery_outbox
        SET status=?, attempts=?, next_attempt_at=?, last_error=?
        WHERE id=?
        """,
        (
            status,
            attempts,
            (current + timedelta(seconds=delay)).isoformat(),
            str(error)[:500],
            delivery_id,
        ),
    )


async def deliver_pending_batch(
    conn: sqlite3.Connection,
    *,
    send_telegram: Callable[[AdminDelivery], Awaitable[str | None]],
    send_email: Callable[[AdminDelivery], Awaitable[str | None]],
    now: datetime | None = None,
    limit: int = 20,
) -> dict[str, int]:
    """Claim and deliver one bounded batch through injected transports."""

    deliveries = claim_pending_deliveries(conn, now=now, limit=limit)
    result = {"claimed": len(deliveries), "sent": 0, "retried": 0, "failed": 0}
    for delivery in deliveries:
        try:
            if delivery.channel == "telegram":
                external_id = await send_telegram(delivery)
            elif delivery.channel == "email":
                external_id = await send_email(delivery)
            else:
                raise RuntimeError("Unsupported administrator delivery channel.")
            mark_delivery_sent(conn, delivery.id, external_id=external_id)
            result["sent"] += 1
        except Exception as exc:  # noqa: BLE001 - transport boundary
            mark_delivery_retry(conn, delivery.id, str(exc), now=now)
            state = conn.execute(
                "SELECT status FROM admin_notification_delivery_outbox WHERE id=?",
                (delivery.id,),
            ).fetchone()
            key = "failed" if state and state["status"] == "failed" else "retried"
            result[key] += 1
        conn.commit()
    return result


class AdminNotificationDeliveryWorker:
    """Single-process wake-up loop over the durable SQLite outbox."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self.last_success_at: str | None = None
        self.last_error_at: str | None = None
        self.last_error: str | None = None

    def start(
        self,
        *,
        connection_factory: Callable[[], sqlite3.Connection],
        send_telegram: Callable[[AdminDelivery], Awaitable[str | None]],
        send_email: Callable[[AdminDelivery], Awaitable[str | None]],
        interval_seconds: float = 30.0,
    ) -> bool:
        if self._task is not None and not self._task.done():
            return False
        self._stopping = False

        async def run() -> None:
            while not self._stopping:
                try:
                    conn = connection_factory()
                    try:
                        result = await deliver_pending_batch(
                            conn,
                            send_telegram=send_telegram,
                            send_email=send_email,
                        )
                    finally:
                        conn.close()
                    if result["sent"]:
                        self.last_success_at = _utc_now().isoformat()
                    self.last_error = None
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - worker watchdog boundary
                    self.last_error_at = _utc_now().isoformat()
                    self.last_error = str(exc)[:500]
                try:
                    await asyncio.sleep(max(1.0, float(interval_seconds)))
                except asyncio.CancelledError:
                    raise

        self._task = asyncio.create_task(run())
        return True

    async def stop(self) -> None:
        self._stopping = True
        task = self._task
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    def status(self) -> dict[str, Any]:
        return {
            "running": bool(self._task is not None and not self._task.done()),
            "lastSuccessAt": self.last_success_at,
            "lastErrorAt": self.last_error_at,
            "lastError": self.last_error,
        }


def build_admin_delivery_transports(
    *,
    telegram_api: Callable[..., Awaitable[dict[str, Any]]],
    send_transactional_email: Callable[[str, str, str], str],
    html_escape: Callable[[str], str],
) -> tuple[
    Callable[[AdminDelivery], Awaitable[str | None]],
    Callable[[AdminDelivery], Awaitable[str | None]],
]:
    def text(delivery: AdminDelivery) -> str:
        payload = delivery.payload
        parts = [
            f"ИЗО АСА · {str(payload.get('title') or 'Уведомление').strip()}",
            str(payload.get("message") or "").strip(),
            str(payload.get("actionUrl") or "").strip(),
        ]
        return "\n\n".join(part for part in parts if part)

    async def send_telegram(delivery: AdminDelivery) -> str | None:
        response = await telegram_api(
            "sendMessage",
            {"chat_id": delivery.destination, "text": text(delivery)},
        )
        result = response.get("result")
        message_id = result.get("message_id") if isinstance(result, dict) else None
        return f"telegram:{message_id}" if message_id is not None else None

    async def send_email(delivery: AdminDelivery) -> str | None:
        payload = delivery.payload
        title = str(payload.get("title") or "Уведомление")
        message = html_escape(str(payload.get("message") or ""))
        action_url = str(payload.get("actionUrl") or "").strip()
        action = (
            f'<p><a href="{html_escape(action_url)}">Открыть в админке</a></p>'
            if action_url
            else ""
        )
        return await asyncio.to_thread(
            send_transactional_email,
            delivery.destination,
            f"ИЗО АСА · {title}",
            f"<p>{message}</p>{action}",
        )

    return send_telegram, send_email
