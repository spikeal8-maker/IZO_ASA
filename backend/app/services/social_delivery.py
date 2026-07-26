"""Durable Telegram delivery for public feed publications.

SQLite remains the source of truth. The in-process worker only claims due
Telegram rows; other networks stay untouched until their own bounded package.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable
from urllib.parse import quote


@dataclass(frozen=True, slots=True)
class SocialDelivery:
    id: str
    publication_id: str
    network: str
    attempts: int


@dataclass(frozen=True, slots=True)
class PublicFeedPublication:
    id: str
    media_type: str
    title: str
    description: str | None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def claim_pending_telegram_deliveries(
    conn: sqlite3.Connection,
    *,
    now: datetime | None = None,
    limit: int = 10,
    lease_seconds: int = 120,
) -> list[SocialDelivery]:
    """Atomically claim due Telegram work and reclaim expired leases."""

    current = now or _utc_now()
    current_iso = current.isoformat()
    conn.execute("BEGIN IMMEDIATE")
    rows = conn.execute(
        """
        SELECT id, publication_id, network, attempts
        FROM social_delivery_outbox
        WHERE network = 'telegram'
          AND (
            status IN ('pending', 'retry')
            OR (status = 'processing' AND next_attempt_at <= ?)
          )
          AND next_attempt_at <= ?
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
            f"UPDATE social_delivery_outbox SET status='processing', "
            f"next_attempt_at=? WHERE id IN ({placeholders})",
            (lease_until, *ids),
        )
    conn.commit()
    return [
        SocialDelivery(
            id=str(row["id"]),
            publication_id=str(row["publication_id"]),
            network=str(row["network"]),
            attempts=int(row["attempts"] or 0),
        )
        for row in rows
    ]


def claim_pending_social_deliveries(
    conn: sqlite3.Connection,
    *,
    network: str,
    now: datetime | None = None,
    limit: int = 10,
    lease_seconds: int = 120,
) -> list[SocialDelivery]:
    if network == "telegram":
        return claim_pending_telegram_deliveries(
            conn, now=now, limit=limit, lease_seconds=lease_seconds
        )
    current = now or _utc_now()
    current_iso = current.isoformat()
    conn.execute("BEGIN IMMEDIATE")
    rows = conn.execute(
        """
        SELECT id, publication_id, network, attempts
        FROM social_delivery_outbox
        WHERE network = ?
          AND (
            status IN ('pending', 'retry')
            OR (status = 'processing' AND next_attempt_at <= ?)
          )
          AND next_attempt_at <= ?
        ORDER BY created_at, id
        LIMIT ?
        """,
        (network, current_iso, current_iso, max(1, min(int(limit), 100))),
    ).fetchall()
    if rows:
        ids = [str(row["id"]) for row in rows]
        placeholders = ",".join("?" for _ in ids)
        lease_until = (current + timedelta(seconds=max(30, int(lease_seconds)))).isoformat()
        conn.execute(
            f"UPDATE social_delivery_outbox SET status='processing', "
            f"next_attempt_at=? WHERE id IN ({placeholders})",
            (lease_until, *ids),
        )
    conn.commit()
    return [
        SocialDelivery(
            id=str(row["id"]), publication_id=str(row["publication_id"]),
            network=str(row["network"]), attempts=int(row["attempts"] or 0),
        )
        for row in rows
    ]


def load_public_feed_publication(
    conn: sqlite3.Connection, publication_id: str
) -> PublicFeedPublication:
    row = conn.execute(
        """
        SELECT id, media_type, title, description
        FROM feed_publications
        WHERE id = ? AND status = 'published'
          AND moderation_status = 'approved'
          AND media_ready_at IS NOT NULL
        """,
        (publication_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("Publication is not publicly deliverable.")
    media_type = str(row["media_type"] or "image")
    if media_type not in {"image", "video"}:
        raise RuntimeError("Unsupported publication media type.")
    return PublicFeedPublication(
        id=str(row["id"]),
        media_type=media_type,
        title=str(row["title"] or "").strip(),
        description=str(row["description"]).strip() if row["description"] else None,
    )


def mark_social_delivery_sent(
    conn: sqlite3.Connection,
    delivery_id: str,
    *,
    external_id: str | None,
    external_url: str | None = None,
    sent_at: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE social_delivery_outbox
        SET status='sent', external_id=?, external_url=?, sent_at=?,
            last_error=NULL
        WHERE id=?
        """,
        (
            external_id,
            external_url,
            sent_at or _utc_now().isoformat(),
            delivery_id,
        ),
    )


def mark_social_delivery_retry(
    conn: sqlite3.Connection,
    delivery_id: str,
    error: str,
    *,
    now: datetime | None = None,
    max_attempts: int = 5,
) -> str:
    row = conn.execute(
        "SELECT attempts FROM social_delivery_outbox WHERE id=?",
        (delivery_id,),
    ).fetchone()
    if row is None:
        return "missing"
    attempts = int(row["attempts"] or 0) + 1
    current = now or _utc_now()
    status = "failed" if attempts >= max(1, int(max_attempts)) else "retry"
    delay = min(3600, 60 * (2 ** max(0, attempts - 1)))
    conn.execute(
        """
        UPDATE social_delivery_outbox
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
    return status


async def deliver_pending_telegram_batch(
    conn: sqlite3.Connection,
    *,
    send_telegram: Callable[
        [SocialDelivery, PublicFeedPublication],
        Awaitable[tuple[str | None, str | None]],
    ],
    now: datetime | None = None,
    limit: int = 10,
) -> dict[str, int]:
    deliveries = claim_pending_telegram_deliveries(conn, now=now, limit=limit)
    result = {"claimed": len(deliveries), "sent": 0, "retried": 0, "failed": 0}
    for delivery in deliveries:
        try:
            publication = load_public_feed_publication(
                conn, delivery.publication_id
            )
            external_id, external_url = await send_telegram(
                delivery, publication
            )
            mark_social_delivery_sent(
                conn,
                delivery.id,
                external_id=external_id,
                external_url=external_url,
            )
            result["sent"] += 1
        except Exception as exc:  # noqa: BLE001 - provider boundary
            status = mark_social_delivery_retry(
                conn, delivery.id, str(exc), now=now
            )
            result["failed" if status == "failed" else "retried"] += 1
        conn.commit()
    return result


async def deliver_pending_social_batch(
    conn: sqlite3.Connection,
    *,
    network: str,
    sender: Callable[
        [SocialDelivery, PublicFeedPublication],
        Awaitable[tuple[str | None, str | None]],
    ],
    now: datetime | None = None,
    limit: int = 10,
) -> dict[str, int]:
    deliveries = claim_pending_social_deliveries(
        conn, network=network, now=now, limit=limit
    )
    result = {"claimed": len(deliveries), "sent": 0, "retried": 0, "failed": 0}
    for delivery in deliveries:
        try:
            publication = load_public_feed_publication(conn, delivery.publication_id)
            external_id, external_url = await sender(delivery, publication)
            mark_social_delivery_sent(
                conn, delivery.id, external_id=external_id, external_url=external_url
            )
            result["sent"] += 1
        except Exception as exc:  # noqa: BLE001 - provider boundary
            status = mark_social_delivery_retry(conn, delivery.id, str(exc), now=now)
            result["failed" if status == "failed" else "retried"] += 1
        conn.commit()
    return result


def build_telegram_social_sender(
    *,
    telegram_api: Callable[..., Awaitable[dict[str, Any]]],
    settings_getter: Callable[[], dict[str, Any]],
    token_getter: Callable[[], str],
    public_site_url_getter: Callable[[], str],
) -> Callable[
    [SocialDelivery, PublicFeedPublication],
    Awaitable[tuple[str | None, str | None]],
]:
    async def send(
        delivery: SocialDelivery, publication: PublicFeedPublication
    ) -> tuple[str | None, str | None]:
        settings = settings_getter()
        networks = (
            settings.get("networks")
            if isinstance(settings.get("networks"), dict)
            else {}
        )
        telegram = networks.get("telegram") or {}
        if not (
            settings.get("masterEnabled")
            and settings.get("autoPublish")
            and telegram.get("enabled")
            and telegram.get("verified")
        ):
            raise RuntimeError("Telegram social delivery is disabled.")
        token = token_getter().strip()
        target = str(telegram.get("targetId") or "").strip()
        base_url = public_site_url_getter().strip().rstrip("/")
        if not token or not target:
            raise RuntimeError("Telegram social credentials are incomplete.")
        if not base_url.startswith("https://"):
            raise RuntimeError("PUBLIC_SITE_URL must use HTTPS.")

        media_path = (
            f"/api/feed/video/{quote(publication.id)}?variant=full"
            if publication.media_type == "video"
            else f"/api/feed/media/{quote(publication.id)}?variant=large"
        )
        media_url = f"{base_url}{media_path}"
        feed_url = f"{base_url}/feed?tab=new#work-{quote(publication.id)}"
        caption_parts = [
            publication.title,
            publication.description or "",
            feed_url,
        ]
        caption = "\n\n".join(part for part in caption_parts if part)[:1024]
        method = "sendVideo" if publication.media_type == "video" else "sendPhoto"
        media_key = "video" if publication.media_type == "video" else "photo"
        response = await telegram_api(
            token=token,
            method=method,
            payload={
                "chat_id": target,
                media_key: media_url,
                "caption": caption,
            },
        )
        body = response.get("result")
        message_id = body.get("message_id") if isinstance(body, dict) else None
        external_id = (
            f"telegram:{message_id}" if message_id is not None else None
        )
        return external_id, None

    return send


def build_max_social_sender(
    *,
    max_api: Callable[..., Awaitable[dict[str, Any]]],
    settings_getter: Callable[[], dict[str, Any]],
    token_getter: Callable[[], str],
    public_site_url_getter: Callable[[], str],
) -> Callable[
    [SocialDelivery, PublicFeedPublication],
    Awaitable[tuple[str | None, str | None]],
]:
    async def send(
        delivery: SocialDelivery, publication: PublicFeedPublication
    ) -> tuple[str | None, str | None]:
        settings = settings_getter()
        networks = settings.get("networks") if isinstance(settings.get("networks"), dict) else {}
        config = networks.get("max") or {}
        if not (
            settings.get("masterEnabled") and settings.get("autoPublish")
            and config.get("enabled") and config.get("verified")
        ):
            raise RuntimeError("MAX social delivery is disabled.")
        token = token_getter().strip()
        target = str(config.get("targetId") or "").strip()
        base_url = public_site_url_getter().strip().rstrip("/")
        if not token or not target:
            raise RuntimeError("MAX social credentials are incomplete.")
        if not base_url.startswith("https://"):
            raise RuntimeError("PUBLIC_SITE_URL must use HTTPS.")
        media_path = (
            f"/api/feed/video/{quote(publication.id)}?variant=full"
            if publication.media_type == "video"
            else f"/api/feed/media/{quote(publication.id)}?variant=large"
        )
        media_url = f"{base_url}{media_path}"
        feed_url = f"{base_url}/feed?tab=new#work-{quote(publication.id)}"
        text = "\n\n".join(
            part for part in (publication.title, publication.description or "", feed_url) if part
        )
        attachments = (
            [{"type": "image", "payload": {"url": media_url}}]
            if publication.media_type == "image"
            else [{"type": "share", "payload": {"url": feed_url}}]
        )
        response = await max_api(
            token=token, target_id=target,
            payload={"text": text[:4000], "attachments": attachments},
        )
        message_id = response.get("message_id") or response.get("messageId") or response.get("id")
        return (f"max:{message_id}" if message_id is not None else None), None

    return send


class SocialDeliveryWorker:
    """Single-process watchdog for durable Telegram syndication."""

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
        send_telegram: Callable[
            [SocialDelivery, PublicFeedPublication],
            Awaitable[tuple[str | None, str | None]],
        ],
        send_max: Callable[
            [SocialDelivery, PublicFeedPublication],
            Awaitable[tuple[str | None, str | None]],
        ] | None = None,
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
                        result = await deliver_pending_telegram_batch(conn, send_telegram=send_telegram)
                        max_result = (
                            await deliver_pending_social_batch(
                                conn, network="max", sender=send_max
                            )
                            if send_max is not None else {"sent": 0}
                        )
                    finally:
                        conn.close()
                    if result["sent"] or max_result["sent"]:
                        self.last_success_at = _utc_now().isoformat()
                    self.last_error = None
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - watchdog boundary
                    self.last_error_at = _utc_now().isoformat()
                    self.last_error = str(exc)[:500]
                await asyncio.sleep(max(1.0, float(interval_seconds)))

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
