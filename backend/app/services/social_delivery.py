"""Durable Telegram delivery for public feed publications.

SQLite remains the source of truth. The in-process worker only claims due
Telegram rows; other networks stay untouched until their own bounded package.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
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
    author_display: str | None = None
    author_handle: str | None = None
    author_code: str | None = None


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
        SELECT f.id, f.media_type, f.title, f.description,
               COALESCE(NULLIF(f.author_display, ''), NULLIF(u.display_name, ''),
                        NULLIF(TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')), '')) AS author_display,
               COALESCE(NULLIF(f.author_handle, ''), NULLIF(u.username, '')) AS author_handle,
               NULLIF(u.public_user_code, '') AS author_code
        FROM feed_publications f
        LEFT JOIN users u ON u.internal_user_id = f.internal_user_id
        WHERE f.id = ? AND f.status = 'published'
          AND f.moderation_status = 'approved'
          AND f.media_ready_at IS NOT NULL
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
        author_display=str(row["author_display"]).strip() if row["author_display"] else None,
        author_handle=str(row["author_handle"]).strip() if row["author_handle"] else None,
        author_code=str(row["author_code"]).strip() if row["author_code"] else None,
    )


def _publication_author(publication: PublicFeedPublication) -> str:
    author = publication.author_display or publication.author_handle or publication.author_code or "участник ИЗО АСА"
    if publication.author_handle and publication.author_handle != author:
        author = f"{author} (@{publication.author_handle.lstrip('@')})"
    return author


def _short_publication_caption(publication: PublicFeedPublication) -> str:
    return f"{publication.title}\n\nРабота автора {_publication_author(publication)}. Больше — в ленте «Новое»."


def _vk_publication_caption(publication: PublicFeedPublication, feed_url: str) -> str:
    description = publication.description or "Новая работа в творческой ленте ИЗО АСА."
    return "\n\n".join((publication.title, description, f"Автор — {_publication_author(publication)}", f"Смотреть новое → {feed_url}"))


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


def enqueue_social_deletions(
    conn: sqlite3.Connection, publication_id: str, *, now: str | None = None
) -> int:
    """Snapshot successful remote deliveries before a publication is hidden."""

    created_at = now or _utc_now().isoformat()
    rows = conn.execute(
        """
        SELECT network, external_id
        FROM social_delivery_outbox
        WHERE publication_id=? AND status='sent' AND external_id IS NOT NULL
          AND network IN ('telegram', 'max', 'vk', 'vk_story')
        """,
        (publication_id,),
    ).fetchall()
    queued = 0
    for row in rows:
        network = str(row["network"])
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO social_delivery_outbox
                (id, publication_id, network, status, attempts, next_attempt_at,
                 external_id, created_at)
            VALUES (?, ?, ?, 'pending', 0, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                publication_id,
                f"delete_{network}",
                created_at,
                str(row["external_id"]),
                created_at,
            ),
        )
        queued += int(cursor.rowcount > 0)
    return queued


async def deliver_pending_social_deletion_batch(
    conn: sqlite3.Connection,
    *,
    sender: Callable[[SocialDelivery, str], Awaitable[None]],
    now: datetime | None = None,
    limit: int = 20,
) -> dict[str, int]:
    result = {"claimed": 0, "sent": 0, "retried": 0, "failed": 0}
    for network in ("delete_telegram", "delete_max", "delete_vk", "delete_vk_story"):
        deliveries = claim_pending_social_deliveries(
            conn, network=network, now=now, limit=limit
        )
        result["claimed"] += len(deliveries)
        for delivery in deliveries:
            row = conn.execute(
                "SELECT external_id FROM social_delivery_outbox WHERE id=?",
                (delivery.id,),
            ).fetchone()
            try:
                if row is None or not row["external_id"]:
                    raise RuntimeError("Remote delivery identifier is missing.")
                await sender(delivery, str(row["external_id"]))
                mark_social_delivery_sent(
                    conn, delivery.id, external_id=str(row["external_id"])
                )
                result["sent"] += 1
            except Exception as exc:  # noqa: BLE001 - provider boundary
                status = mark_social_delivery_retry(
                    conn, delivery.id, str(exc), now=now
                )
                result["failed" if status == "failed" else "retried"] += 1
            conn.commit()
    return result


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
    telegram_image_api: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    telegram_video_api: Callable[..., Awaitable[dict[str, Any]]] | None = None,
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
        feed_url = f"{base_url}/feed?tab=new"
        caption = _short_publication_caption(publication)[:1024]
        reply_markup = json.dumps({"inline_keyboard": [[{"text": "Открыть ленту", "url": feed_url}]]}, ensure_ascii=False)
        method = "sendVideo" if publication.media_type == "video" else "sendPhoto"
        media_key = "video" if publication.media_type == "video" else "photo"
        uploader = telegram_video_api if publication.media_type == "video" else telegram_image_api
        response = await uploader(
            token=token, target_id=target, caption=caption, media_url=media_url,
            reply_markup=reply_markup,
        ) if uploader is not None else await telegram_api(
            token=token,
            method=method,
            payload={
                "chat_id": target,
                media_key: media_url,
                "caption": caption,
                "reply_markup": reply_markup,
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
    max_video_publisher: Callable[..., Awaitable[dict[str, Any]]] | None = None,
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
        feed_url = f"{base_url}/feed?tab=new"
        text = _short_publication_caption(publication)
        attachments = (
            [{"type": "image", "payload": {"url": media_url}}]
            if publication.media_type == "image"
            else []
        )
        attachments.append({"type": "inline_keyboard", "payload": {"buttons": [[{"type": "link", "text": "Открыть ленту", "url": feed_url}]]}})
        response = await max_video_publisher(
            token=token, target_id=target, message=text[:4000],
            media_url=media_url, feed_url=feed_url,
        ) if publication.media_type == "video" and max_video_publisher is not None else await max_api(
            token=token, target_id=target,
            payload={"text": text[:4000], "attachments": attachments},
        )
        response_message = response.get("message") if isinstance(response.get("message"), dict) else {}
        response_body = response_message.get("body") if isinstance(response_message.get("body"), dict) else {}
        message_id = response.get("message_id") or response.get("messageId") or response.get("id") or response_message.get("message_id") or response_message.get("messageId") or response_message.get("id") or response_body.get("mid")
        return (f"max:{message_id}" if message_id is not None else None), None

    return send


def build_vk_social_sender(
    *,
    vk_api: Callable[..., Awaitable[dict[str, Any]]],
    settings_getter: Callable[[], dict[str, Any]],
    token_getter: Callable[[], str],
    public_site_url_getter: Callable[[], str],
    media_token_getter: Callable[[], str] = lambda: "",
    vk_image_publisher: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    vk_video_publisher: Callable[..., Awaitable[dict[str, Any]]] | None = None,
) -> Callable[
    [SocialDelivery, PublicFeedPublication],
    Awaitable[tuple[str | None, str | None]],
]:
    async def send(
        delivery: SocialDelivery, publication: PublicFeedPublication
    ) -> tuple[str | None, str | None]:
        settings = settings_getter()
        networks = settings.get("networks") if isinstance(settings.get("networks"), dict) else {}
        config = networks.get("vk") or {}
        if not (
            settings.get("masterEnabled") and settings.get("autoPublish")
            and config.get("enabled") and config.get("verified")
        ):
            raise RuntimeError("VK social delivery is disabled.")
        token = token_getter().strip()
        media_token = media_token_getter().strip()
        group_id = str(config.get("targetId") or "").strip().lstrip("-")
        base_url = public_site_url_getter().strip().rstrip("/")
        if not token or not group_id:
            raise RuntimeError("VK social credentials are incomplete.")
        if ((publication.media_type == "image" and vk_image_publisher is not None)
                or (publication.media_type == "video" and vk_video_publisher is not None)) and not media_token:
            raise RuntimeError("VK user media token is required for media publication.")
        feed_url = f"{base_url}/feed?tab=new"
        media_url = (
            f"{base_url}/api/feed/video/{quote(publication.id)}?variant=full"
            if publication.media_type == "video"
            else f"{base_url}/api/feed/media/{quote(publication.id)}?variant=large"
        )
        message = _vk_publication_caption(publication, feed_url)
        publisher = vk_video_publisher if publication.media_type == "video" else vk_image_publisher
        response = await publisher(
            vk_api=vk_api, token=token, media_token=media_token, group_id=group_id,
            message=message[:15000], media_url=media_url,
        ) if publisher is not None else await vk_api(
            token=token,
            method="wall.post",
            params={
                "owner_id": f"-{group_id}",
                "from_group": 1,
                "message": message[:15000],
            },
        )
        body = response.get("response") if isinstance(response.get("response"), dict) else {}
        post_id = body.get("post_id")
        external_url = f"https://vk.com/wall-{group_id}_{post_id}" if post_id is not None else None
        media_ref = str(response.get("_media_ref") or "")
        suffix = f":{media_ref}" if media_ref else ""
        return (f"vk:{post_id}{suffix}" if post_id is not None else None), external_url

    return send


def build_vk_story_sender(
    *,
    settings_getter: Callable[[], dict[str, Any]],
    media_token_getter: Callable[[], str],
    public_site_url_getter: Callable[[], str],
    vk_story_publisher: Callable[..., Awaitable[dict[str, Any]]],
) -> Callable[
    [SocialDelivery, PublicFeedPublication],
    Awaitable[tuple[str | None, str | None]],
]:
    async def send(
        delivery: SocialDelivery, publication: PublicFeedPublication
    ) -> tuple[str | None, str | None]:
        settings = settings_getter()
        networks = settings.get("networks") if isinstance(settings.get("networks"), dict) else {}
        config = networks.get("vk") or {}
        if not (
            settings.get("masterEnabled") and settings.get("autoPublish")
            and config.get("storyEnabled") and config.get("verified")
        ):
            raise RuntimeError("VK Stories delivery is disabled.")
        token = media_token_getter().strip()
        group_id = str(config.get("targetId") or "").strip().lstrip("-")
        base_url = public_site_url_getter().strip().rstrip("/")
        if not token or not group_id:
            raise RuntimeError("VK Stories credentials are incomplete.")
        media_url = (
            f"{base_url}/api/feed/video/{quote(publication.id)}?variant=full"
            if publication.media_type == "video"
            else f"{base_url}/api/feed/media/{quote(publication.id)}?variant=large"
        )
        response = await vk_story_publisher(
            media_token=token, group_id=group_id,
            media_type=publication.media_type, media_url=media_url,
            feed_url=f"{base_url}/feed?tab=new",
        )
        body = response.get("response")
        items = body.get("items") if isinstance(body, dict) else body
        story = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}
        story_id, owner_id = story.get("id"), story.get("owner_id")
        if story_id is None or owner_id is None:
            shape = sorted(body.keys()) if isinstance(body, dict) else type(body).__name__
            raise RuntimeError(f"VK Stories did not confirm a story id; response shape={shape}.")
        external_id = f"vk_story:{owner_id}_{story_id}"
        return external_id, None

    return send


def build_social_deletion_sender(
    *,
    settings_getter: Callable[[], dict[str, Any]],
    secret_getter: Callable[[str], str],
    telegram_api: Callable[..., Awaitable[dict[str, Any]]],
    max_api: Callable[..., Awaitable[dict[str, Any]]],
    vk_api: Callable[..., Awaitable[dict[str, Any]]],
) -> Callable[[SocialDelivery, str], Awaitable[None]]:
    async def delete(delivery: SocialDelivery, external_id: str) -> None:
        settings = settings_getter()
        networks = settings.get("networks") if isinstance(settings.get("networks"), dict) else {}
        if delivery.network == "delete_telegram":
            config = networks.get("telegram") or {}
            await telegram_api(
                token=secret_getter("social_telegram_access_token"),
                method="deleteMessage",
                payload={"chat_id": str(config.get("targetId") or ""),
                         "message_id": external_id.removeprefix("telegram:")},
            )
        elif delivery.network == "delete_max":
            await max_api(
                token=secret_getter("social_max_access_token"), method="DELETE",
                path="/messages",
                params={"message_id": external_id.removeprefix("max:")},
            )
        elif delivery.network == "delete_vk":
            parts = external_id.removeprefix("vk:").split(":", 1)
            group_id = str((networks.get("vk") or {}).get("targetId") or "").lstrip("-")
            await vk_api(
                token=secret_getter("social_vk_access_token"),
                method="wall.delete",
                params={"owner_id": f"-{group_id}", "post_id": parts[0]},
            )
            media_ref = parts[1] if len(parts) > 1 else ""
            if media_ref.startswith(("photo", "video")):
                kind = "photo" if media_ref.startswith("photo") else "video"
                owner_id, media_id = media_ref.removeprefix(kind).rsplit("_", 1)
                await vk_api(
                    token=secret_getter("social_vk_media_access_token"),
                    method=f"{kind}s.delete" if kind == "photo" else "video.delete",
                    params={"owner_id": owner_id, f"{kind}_id": media_id},
                )
        elif delivery.network == "delete_vk_story":
            owner_id, story_id = external_id.removeprefix("vk_story:").rsplit("_", 1)
            await vk_api(
                token=secret_getter("social_vk_media_access_token"),
                method="stories.delete",
                params={"owner_id": owner_id, "story_id": story_id},
            )
        else:
            raise RuntimeError("Unsupported social deletion network.")

    return delete


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
        send_vk: Callable[
            [SocialDelivery, PublicFeedPublication],
            Awaitable[tuple[str | None, str | None]],
        ] | None = None,
        send_vk_story: Callable[
            [SocialDelivery, PublicFeedPublication],
            Awaitable[tuple[str | None, str | None]],
        ] | None = None,
        delete_social: Callable[[SocialDelivery, str], Awaitable[None]] | None = None,
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
                        vk_result = (
                            await deliver_pending_social_batch(
                                conn, network="vk", sender=send_vk
                            )
                            if send_vk is not None else {"sent": 0}
                        )
                        vk_story_result = (
                            await deliver_pending_social_batch(
                                conn, network="vk_story", sender=send_vk_story
                            )
                            if send_vk_story is not None else {"sent": 0}
                        )
                        delete_result = (
                            await deliver_pending_social_deletion_batch(
                                conn, sender=delete_social
                            )
                            if delete_social is not None else {"sent": 0}
                        )
                    finally:
                        conn.close()
                    if result["sent"] or max_result["sent"] or vk_result["sent"] or vk_story_result["sent"] or delete_result["sent"]:
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
