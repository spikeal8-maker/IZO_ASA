import sqlite3

from app.database.migrations import apply_admin_notifications_migration
from app.services.admin_notifications import (
    create_notification,
    enqueue_configured_social_deliveries,
    enqueue_social_deliveries,
    list_notifications,
    mark_notifications_read,
    openrouter_change_notification,
)


def connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
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
        ('{"autoPublish":false,"networks":{"telegram":{"enabled":true}}}',),
    )
    assert enqueue_configured_social_deliveries(conn, "pub-safe") == 0
    conn.execute(
        "UPDATE admin_settings SET value_json = ? WHERE key = 'social_syndication'",
        ('{"autoPublish":true,"networks":{"telegram":{"enabled":true},"vk":{"enabled":true}}}',),
    )
    assert enqueue_configured_social_deliveries(conn, "pub-safe") == 2
    assert enqueue_configured_social_deliveries(conn, "pub-safe") == 0
