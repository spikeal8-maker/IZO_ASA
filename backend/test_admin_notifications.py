import asyncio
import sqlite3
from datetime import datetime, timezone

from app.database.migrations import (
    apply_admin_notification_delivery_migration,
    apply_admin_notifications_migration,
)
from app.services.admin_notifications import (
    create_notification,
    enqueue_configured_social_deliveries,
    enqueue_social_deliveries,
    list_notifications,
    mark_notifications_read,
    openrouter_change_notification,
)
from app.services.admin_notification_delivery import (
    AdminNotificationDeliveryWorker,
    claim_pending_deliveries,
    deliver_pending_batch,
    mark_delivery_retry,
    mark_delivery_sent,
)


def connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def prepare_delivery_connection() -> sqlite3.Connection:
    conn = connection()
    conn.execute(
        "CREATE TABLE admin_settings "
        "(key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT)"
    )
    apply_admin_notifications_migration(
        conn, applied_at="2026-07-24T00:00:00+00:00"
    )
    apply_admin_notification_delivery_migration(
        conn, applied_at="2026-07-24T00:00:01+00:00"
    )
    return conn


def test_notification_is_deduplicated_and_marked_read():
    conn = connection()
    apply_admin_notifications_migration(conn, applied_at="2026-07-24T00:00:00+00:00")
    first = create_notification(
        conn,
        dedupe_key="provider:1",
        category="provider",
        severity="warning",
        title="Provider",
        message="Unavailable",
    )
    second = create_notification(
        conn,
        dedupe_key="provider:1",
        category="provider",
        severity="warning",
        title="Provider",
        message="Unavailable",
    )
    assert first[1] is True
    assert second == (first[0], False)
    assert list_notifications(conn)["unread"] == 1
    assert mark_notifications_read(conn, [first[0]]) == 1
    assert list_notifications(conn)["unread"] == 0


def test_openrouter_summary_and_social_outbox_are_idempotent():
    conn = connection()
    apply_admin_notifications_migration(conn, applied_at="2026-07-24T00:00:00+00:00")
    lifecycle = {
        "refreshedAt": "2026-07-24T01:00:00+00:00",
        "changes": {
            "images": {"added": ["a"], "removed": [], "priceChanged": [], "unpriced": ["a"]},
            "videos": {"added": [], "removed": ["b"], "priceChanged": ["c"], "unpriced": []},
        },
    }
    assert openrouter_change_notification(conn, lifecycle)[1] is True
    assert openrouter_change_notification(conn, lifecycle)[1] is False
    assert enqueue_social_deliveries(conn, publication_id="pub-1", networks=["telegram", "vk"]) == 2
    assert enqueue_social_deliveries(conn, publication_id="pub-1", networks=["telegram", "vk"]) == 0


def test_configured_social_outbox_stays_off_until_admin_enables_autopublish():
    conn = connection()
    conn.execute("CREATE TABLE admin_settings (key TEXT PRIMARY KEY, value_json TEXT)")
    apply_admin_notifications_migration(conn, applied_at="2026-07-24T00:00:00+00:00")
    conn.execute(
        "INSERT INTO admin_settings VALUES ('social_syndication', ?)",
        ('{"masterEnabled":true,"autoPublish":false,"networks":{"telegram":{"enabled":true,"verified":true}}}',),
    )
    assert enqueue_configured_social_deliveries(conn, "pub-safe") == 0
    conn.execute(
        "UPDATE admin_settings SET value_json = ? WHERE key = 'social_syndication'",
        ('{"masterEnabled":false,"autoPublish":true,"networks":{"telegram":{"enabled":true,"verified":true}}}',),
    )
    assert enqueue_configured_social_deliveries(conn, "pub-safe") == 0
    conn.execute(
        "UPDATE admin_settings SET value_json = ? WHERE key = 'social_syndication'",
        ('{"masterEnabled":true,"autoPublish":true,"networks":{"telegram":{"enabled":true,"verified":false}}}',),
    )
    assert enqueue_configured_social_deliveries(conn, "pub-safe") == 0
    conn.execute(
        "UPDATE admin_settings SET value_json = ? WHERE key = 'social_syndication'",
        ('{"masterEnabled":true,"autoPublish":true,"networks":{"telegram":{"enabled":true,"verified":true},"vk":{"enabled":true,"verified":true}}}',),
    )
    assert enqueue_configured_social_deliveries(conn, "pub-safe") == 2
    assert enqueue_configured_social_deliveries(conn, "pub-safe") == 0

    conn.execute("DELETE FROM social_delivery_outbox")
    conn.execute(
        "UPDATE admin_settings SET value_json = ? WHERE key = 'social_syndication'",
        ('{"masterEnabled":true,"autoPublish":true,"networks":{"vk":{"enabled":true,"storyEnabled":true,"verified":true}}}',),
    )
    assert enqueue_configured_social_deliveries(conn, "pub-story") == 2
    assert {
        row["network"] for row in conn.execute(
            "SELECT network FROM social_delivery_outbox WHERE publication_id='pub-story'"
        )
    } == {"vk", "vk_story"}


def test_notification_delivery_is_atomic_and_idempotent():
    conn = prepare_delivery_connection()
    conn.execute(
        "INSERT INTO admin_settings VALUES ('admin_notification_settings', ?, ?)",
        (
            '{"telegramEnabled":true,"telegramChatId":"-100123",'
            '"emailEnabled":true,"emailAddress":"admin@example.test",'
            '"minimumSeverity":"warning","digestMode":"immediate"}',
            "2026-07-24T00:00:00+00:00",
        ),
    )

    notification_id, created = create_notification(
        conn,
        dedupe_key="provider:delivery:1",
        category="provider",
        severity="warning",
        title="Provider unavailable",
        message="The provider did not respond.",
        created_at="2026-07-24T01:00:00+00:00",
    )
    duplicate = create_notification(
        conn,
        dedupe_key="provider:delivery:1",
        category="provider",
        severity="warning",
        title="Provider unavailable",
        message="The provider did not respond.",
        created_at="2026-07-24T01:00:00+00:00",
    )

    assert created is True
    assert duplicate == (notification_id, False)
    rows = conn.execute(
        "SELECT channel, destination, status FROM admin_notification_delivery_outbox "
        "ORDER BY channel"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("email", "admin@example.test", "pending"),
        ("telegram", "-100123", "pending"),
    ]


def test_delivery_severity_filter_and_disabled_channels_are_safe():
    conn = prepare_delivery_connection()
    conn.execute(
        "INSERT INTO admin_settings VALUES ('admin_notification_settings', ?, ?)",
        (
            '{"telegramEnabled":true,"telegramChatId":"42",'
            '"emailEnabled":false,"emailAddress":"admin@example.test",'
            '"minimumSeverity":"critical","digestMode":"immediate"}',
            "2026-07-24T00:00:00+00:00",
        ),
    )

    create_notification(
        conn,
        dedupe_key="provider:delivery:info",
        category="provider",
        severity="warning",
        title="Warning",
        message="Below threshold.",
    )
    create_notification(
        conn,
        dedupe_key="provider:delivery:critical",
        category="provider",
        severity="critical",
        title="Critical",
        message="Must be delivered.",
    )

    rows = conn.execute(
        "SELECT channel, destination FROM admin_notification_delivery_outbox"
    ).fetchall()
    assert [tuple(row) for row in rows] == [("telegram", "42")]


def test_delivery_claim_lease_retry_and_sent_lifecycle():
    conn = prepare_delivery_connection()
    conn.execute(
        """
        INSERT INTO admin_notification_delivery_outbox
            (id, notification_id, channel, destination, status, attempts,
             next_attempt_at, payload_json, created_at)
        VALUES ('delivery-1', 'notice-1', 'telegram', '42', 'pending', 0,
                '2026-07-24T01:00:00+00:00', '{}',
                '2026-07-24T01:00:00+00:00')
        """
    )
    conn.commit()
    now = datetime(2026, 7, 24, 1, 0, tzinfo=timezone.utc)

    claimed = claim_pending_deliveries(conn, now=now, lease_seconds=60)
    assert [item.id for item in claimed] == ["delivery-1"]
    assert claim_pending_deliveries(conn, now=now, lease_seconds=60) == []

    mark_delivery_retry(conn, "delivery-1", "temporary failure", now=now)
    row = conn.execute(
        "SELECT status, attempts, last_error FROM admin_notification_delivery_outbox"
    ).fetchone()
    assert tuple(row) == ("retry", 1, "temporary failure")
    conn.commit()

    later = datetime(2026, 7, 24, 1, 1, tzinfo=timezone.utc)
    assert [item.id for item in claim_pending_deliveries(conn, now=later)] == [
        "delivery-1"
    ]
    mark_delivery_sent(
        conn, "delivery-1", external_id="telegram:100", sent_at=later.isoformat()
    )
    row = conn.execute(
        "SELECT status, external_id, sent_at "
        "FROM admin_notification_delivery_outbox"
    ).fetchone()
    assert tuple(row) == ("sent", "telegram:100", later.isoformat())


def test_delivery_batch_uses_injected_transports_only():
    conn = prepare_delivery_connection()
    conn.execute(
        "INSERT INTO admin_notifications "
        "(id, dedupe_key, category, severity, title, message, created_at) "
        "VALUES ('notice-1', 'notice:1', 'provider', 'critical', 'Title', "
        "'Message', '2026-07-24T01:00:00+00:00')"
    )
    for delivery_id, channel, destination in (
        ("delivery-tg", "telegram", "42"),
        ("delivery-email", "email", "admin@example.test"),
    ):
        conn.execute(
            """
            INSERT INTO admin_notification_delivery_outbox
                (id, notification_id, channel, destination, status, attempts,
                 next_attempt_at, payload_json, created_at)
            VALUES (?, 'notice-1', ?, ?, 'pending', 0,
                    '2026-07-24T01:00:00+00:00',
                    '{"title":"Title","message":"Message"}',
                    '2026-07-24T01:00:00+00:00')
            """,
            (delivery_id, channel, destination),
        )
    conn.commit()
    calls = []

    async def send_telegram(delivery):
        calls.append(("telegram", delivery.destination))
        return "telegram:10"

    async def send_email(delivery):
        calls.append(("email", delivery.destination))
        return "email:10"

    result = asyncio.run(
        deliver_pending_batch(
            conn,
            send_telegram=send_telegram,
            send_email=send_email,
            now=datetime(2026, 7, 24, 1, 0, tzinfo=timezone.utc),
        )
    )

    assert result == {"claimed": 2, "sent": 2, "retried": 0, "failed": 0}
    assert calls == [
        ("email", "admin@example.test"),
        ("telegram", "42"),
    ]
    statuses = conn.execute(
        "SELECT status FROM admin_notification_delivery_outbox ORDER BY id"
    ).fetchall()
    assert [row["status"] for row in statuses] == ["sent", "sent"]


def test_delivery_batch_retries_transport_failures_without_losing_work():
    conn = prepare_delivery_connection()
    conn.execute(
        "INSERT INTO admin_notifications "
        "(id, dedupe_key, category, severity, title, message, created_at) "
        "VALUES ('notice-1', 'notice:1', 'provider', 'critical', 'Title', "
        "'Message', '2026-07-24T01:00:00+00:00')"
    )
    conn.execute(
        """
        INSERT INTO admin_notification_delivery_outbox
            (id, notification_id, channel, destination, status, attempts,
             next_attempt_at, payload_json, created_at)
        VALUES ('delivery-1', 'notice-1', 'telegram', '42', 'pending', 0,
                '2026-07-24T01:00:00+00:00', '{}',
                '2026-07-24T01:00:00+00:00')
        """
    )
    conn.commit()

    async def fail(_delivery):
        raise RuntimeError("fake transport unavailable")

    result = asyncio.run(
        deliver_pending_batch(
            conn,
            send_telegram=fail,
            send_email=fail,
            now=datetime(2026, 7, 24, 1, 0, tzinfo=timezone.utc),
        )
    )
    assert result == {"claimed": 1, "sent": 0, "retried": 1, "failed": 0}
    row = conn.execute(
        "SELECT status, attempts, last_error "
        "FROM admin_notification_delivery_outbox"
    ).fetchone()
    assert tuple(row) == ("retry", 1, "fake transport unavailable")


def test_delivery_worker_has_single_owner_and_stops_cleanly(tmp_path):
    path = tmp_path / "delivery-worker.sqlite3"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE admin_settings "
        "(key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT)"
    )
    apply_admin_notifications_migration(
        conn, applied_at="2026-07-24T00:00:00+00:00"
    )
    apply_admin_notification_delivery_migration(
        conn, applied_at="2026-07-24T00:00:01+00:00"
    )
    conn.commit()
    conn.close()

    def db():
        worker_conn = sqlite3.connect(path)
        worker_conn.row_factory = sqlite3.Row
        return worker_conn

    async def fake_send(_delivery):
        raise AssertionError("Empty queue must not call a transport.")

    async def scenario():
        worker = AdminNotificationDeliveryWorker()
        assert worker.start(
            connection_factory=db,
            send_telegram=fake_send,
            send_email=fake_send,
            interval_seconds=1,
        ) is True
        assert worker.start(
            connection_factory=db,
            send_telegram=fake_send,
            send_email=fake_send,
            interval_seconds=1,
        ) is False
        await asyncio.sleep(0)
        assert worker.status()["running"] is True
        await worker.stop()
        assert worker.status()["running"] is False

    asyncio.run(scenario())
