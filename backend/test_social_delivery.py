from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

from app.services.social_delivery import (
    build_max_social_sender,
    build_telegram_social_sender,
    claim_pending_telegram_deliveries,
    deliver_pending_telegram_batch,
)


NOW = datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc)


def database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE social_delivery_outbox (
            id TEXT PRIMARY KEY, publication_id TEXT NOT NULL,
            network TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT NOT NULL,
            external_id TEXT, external_url TEXT, last_error TEXT,
            created_at TEXT NOT NULL, sent_at TEXT
        );
        CREATE TABLE feed_publications (
            id TEXT PRIMARY KEY, media_type TEXT NOT NULL, title TEXT NOT NULL,
            description TEXT, internal_user_id TEXT, author_display TEXT,
            author_handle TEXT, status TEXT NOT NULL,
            moderation_status TEXT NOT NULL, media_ready_at TEXT
        );
        CREATE TABLE users (
            internal_user_id TEXT PRIMARY KEY, display_name TEXT,
            first_name TEXT, last_name TEXT, username TEXT,
            public_user_code TEXT
        );
        """
    )
    return conn


def add_delivery(
    conn: sqlite3.Connection,
    *,
    delivery_id: str = "delivery-1",
    publication_id: str = "publication-1",
    network: str = "telegram",
    status: str = "pending",
    next_attempt_at: datetime = NOW,
) -> None:
    conn.execute(
        """
        INSERT INTO social_delivery_outbox
            (id, publication_id, network, status, next_attempt_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            delivery_id,
            publication_id,
            network,
            status,
            next_attempt_at.isoformat(),
            NOW.isoformat(),
        ),
    )
    conn.commit()


def add_publication(
    conn: sqlite3.Connection,
    *,
    media_type: str = "image",
    status: str = "published",
    moderation_status: str = "approved",
    media_ready_at: str | None = NOW.isoformat(),
) -> None:
    conn.execute(
        """
        INSERT INTO feed_publications
            (id, media_type, title, description, status,
             moderation_status, media_ready_at)
        VALUES ('publication-1', ?, 'Работа', 'Описание', ?, ?, ?)
        """,
        (media_type, status, moderation_status, media_ready_at),
    )
    conn.commit()


def test_claim_is_atomic_and_does_not_claim_other_networks() -> None:
    conn = database()
    add_delivery(conn)
    add_delivery(conn, delivery_id="vk-1", network="vk")

    claimed = claim_pending_telegram_deliveries(conn, now=NOW)
    repeated = claim_pending_telegram_deliveries(conn, now=NOW)

    assert [item.id for item in claimed] == ["delivery-1"]
    assert repeated == []
    assert conn.execute(
        "SELECT status FROM social_delivery_outbox WHERE id='vk-1'"
    ).fetchone()["status"] == "pending"


def test_expired_lease_is_reclaimed() -> None:
    conn = database()
    add_delivery(
        conn,
        status="processing",
        next_attempt_at=NOW - timedelta(seconds=1),
    )

    claimed = claim_pending_telegram_deliveries(conn, now=NOW)

    assert [item.id for item in claimed] == ["delivery-1"]


def test_success_marks_delivery_sent() -> None:
    conn = database()
    add_delivery(conn)
    add_publication(conn)

    async def fake_send(delivery, publication):
        assert delivery.publication_id == publication.id
        return "telegram:42", "https://t.me/channel/42"

    result = asyncio.run(
        deliver_pending_telegram_batch(
            conn, send_telegram=fake_send, now=NOW
        )
    )
    row = conn.execute(
        "SELECT * FROM social_delivery_outbox WHERE id='delivery-1'"
    ).fetchone()

    assert result == {"claimed": 1, "sent": 1, "retried": 0, "failed": 0}
    assert row["status"] == "sent"
    assert row["external_id"] == "telegram:42"
    assert row["last_error"] is None


def test_missing_or_hidden_publication_retries_without_sending() -> None:
    conn = database()
    add_delivery(conn)
    add_publication(conn, status="hidden")
    called = False

    async def fake_send(_delivery, _publication):
        nonlocal called
        called = True
        return None, None

    result = asyncio.run(
        deliver_pending_telegram_batch(
            conn, send_telegram=fake_send, now=NOW
        )
    )
    row = conn.execute(
        "SELECT * FROM social_delivery_outbox WHERE id='delivery-1'"
    ).fetchone()

    assert called is False
    assert result["retried"] == 1
    assert row["status"] == "retry"
    assert row["attempts"] == 1


def test_retry_becomes_failed_after_five_attempts() -> None:
    conn = database()
    add_delivery(conn)
    add_publication(conn)
    conn.execute(
        "UPDATE social_delivery_outbox SET attempts=4 WHERE id='delivery-1'"
    )
    conn.commit()

    async def failing_send(_delivery, _publication):
        raise RuntimeError("provider unavailable")

    result = asyncio.run(
        deliver_pending_telegram_batch(
            conn, send_telegram=failing_send, now=NOW
        )
    )
    row = conn.execute(
        "SELECT status, attempts, last_error FROM social_delivery_outbox"
    ).fetchone()

    assert result["failed"] == 1
    assert (row["status"], row["attempts"]) == ("failed", 5)
    assert row["last_error"] == "provider unavailable"


def test_sender_builds_https_photo_request_without_exposing_token() -> None:
    calls = []

    async def fake_api(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "result": {"message_id": 77}}

    sender = build_telegram_social_sender(
        telegram_api=fake_api,
        settings_getter=lambda: {
            "masterEnabled": True,
            "autoPublish": True,
            "networks": {
                "telegram": {
                    "enabled": True,
                    "verified": True,
                    "targetId": "@izo_channel",
                }
            },
        },
        token_getter=lambda: "secret-token",
        public_site_url_getter=lambda: "https://izo.example",
    )
    conn = database()
    add_delivery(conn)
    add_publication(conn)
    result = asyncio.run(
        deliver_pending_telegram_batch(conn, send_telegram=sender, now=NOW)
    )

    assert result["sent"] == 1
    assert calls[0]["token"] == "secret-token"
    assert calls[0]["method"] == "sendPhoto"
    assert calls[0]["payload"]["photo"].endswith("/api/feed/media/publication-1?variant=large")
    assert calls[0]["payload"]["caption"].startswith("Работа\n\n")
    assert "Описание" not in calls[0]["payload"]["caption"]
    assert "https://" not in calls[0]["payload"]["caption"]
    assert "https://izo.example/feed?tab=new" in calls[0]["payload"]["reply_markup"]


def test_sender_refuses_disabled_or_non_https_configuration() -> None:
    async def fake_api(**_kwargs):
        raise AssertionError("must not call provider")

    publication_settings = {
        "masterEnabled": False,
        "autoPublish": True,
        "networks": {
            "telegram": {
                "enabled": True,
                "verified": True,
                "targetId": "@channel",
            }
        },
    }
    sender = build_telegram_social_sender(
        telegram_api=fake_api,
        settings_getter=lambda: publication_settings,
        token_getter=lambda: "secret",
        public_site_url_getter=lambda: "http://127.0.0.1:5173",
    )
    conn = database()
    add_delivery(conn)
    add_publication(conn)

    result = asyncio.run(
        deliver_pending_telegram_batch(conn, send_telegram=sender, now=NOW)
    )

    assert result["retried"] == 1


def test_max_sender_uses_public_image_url_and_channel_id() -> None:
    calls = []

    async def fake_max_api(**kwargs):
        calls.append(kwargs)
        return {"message": {"body": {"mid": "max-message-7"}}}

    sender = build_max_social_sender(
        max_api=fake_max_api,
        settings_getter=lambda: {
            "masterEnabled": True,
            "autoPublish": True,
            "networks": {
                "max": {
                    "enabled": True,
                    "verified": True,
                    "targetId": "-700000000001",
                }
            },
        },
        token_getter=lambda: "max-secret",
        public_site_url_getter=lambda: "https://izo.example",
    )
    conn = database()
    add_delivery(conn, network="max")
    add_publication(conn)
    delivery = conn.execute(
        "SELECT id, publication_id, network, attempts "
        "FROM social_delivery_outbox WHERE network='max'"
    ).fetchone()
    publication = conn.execute(
        "SELECT id, media_type, title, description FROM feed_publications"
    ).fetchone()
    from app.services.social_delivery import PublicFeedPublication, SocialDelivery

    result = asyncio.run(sender(
        SocialDelivery(**dict(delivery)),
        PublicFeedPublication(**dict(publication)),
    ))

    assert result == ("max:max-message-7", None)
    assert calls[0]["token"] == "max-secret"
    assert calls[0]["target_id"] == "-700000000001"
    assert calls[0]["payload"]["attachments"][0] == {
        "type": "image",
        "payload": {
            "url": "https://izo.example/api/feed/media/publication-1?variant=large"
        },
    }
    assert calls[0]["payload"]["attachments"][1]["type"] == "inline_keyboard"
    assert calls[0]["payload"]["text"].startswith("Работа\n\n")
    assert "https://" not in calls[0]["payload"]["text"]


def test_telegram_video_uses_native_uploader_and_feed_button() -> None:
    calls = []

    async def fake_api(**_kwargs):
        raise AssertionError("generic Telegram API must not be used")

    async def fake_video(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "result": {"message_id": 91}}

    sender = build_telegram_social_sender(
        telegram_api=fake_api, telegram_video_api=fake_video,
        settings_getter=lambda: {"masterEnabled": True, "autoPublish": True,
            "networks": {"telegram": {"enabled": True, "verified": True, "targetId": "@izo"}}},
        token_getter=lambda: "secret", public_site_url_getter=lambda: "https://izo.example",
    )
    conn = database()
    add_delivery(conn)
    add_publication(conn, media_type="video")
    result = asyncio.run(deliver_pending_telegram_batch(conn, send_telegram=sender, now=NOW))

    assert result["sent"] == 1
    assert calls[0]["media_url"].endswith("/api/feed/video/publication-1?variant=full")
    assert "https://izo.example/feed?tab=new" in calls[0]["reply_markup"]


def test_max_video_uses_native_uploader() -> None:
    calls = []

    async def fake_max(**_kwargs):
        raise AssertionError("generic MAX send must not be used")

    async def fake_video(**kwargs):
        calls.append(kwargs)
        return {"message": {"body": {"mid": "video-2"}}}

    sender = build_max_social_sender(
        max_api=fake_max, max_video_publisher=fake_video,
        settings_getter=lambda: {"masterEnabled": True, "autoPublish": True,
            "networks": {"max": {"enabled": True, "verified": True, "targetId": "-7"}}},
        token_getter=lambda: "secret", public_site_url_getter=lambda: "https://izo.example",
    )
    from app.services.social_delivery import PublicFeedPublication, SocialDelivery
    result = asyncio.run(sender(
        SocialDelivery("d", "p", "max", 0),
        PublicFeedPublication("p", "video", "Название", "Полное описание"),
    ))

    assert result == ("max:video-2", None)
    assert calls[0]["media_url"].endswith("/api/feed/video/p?variant=full")
    assert calls[0]["feed_url"] == "https://izo.example/feed?tab=new"
    assert "https://" not in calls[0]["message"]
