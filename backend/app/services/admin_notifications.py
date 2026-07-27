"""Durable administrator notifications and social-delivery queue primitives."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable


SEVERITIES = {"info", "warning", "critical"}
SOCIAL_NETWORKS = {"telegram", "max", "vk", "vk_story", "instagram", "ok"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_notification(
    conn: sqlite3.Connection,
    *,
    dedupe_key: str,
    category: str,
    severity: str,
    title: str,
    message: str,
    details: dict[str, Any] | None = None,
    action_url: str | None = None,
    created_at: str | None = None,
) -> tuple[str, bool]:
    if severity not in SEVERITIES:
        raise ValueError("INVALID_NOTIFICATION_SEVERITY")
    notification_id = str(uuid.uuid4())
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO admin_notifications
            (id, dedupe_key, category, severity, title, message, details_json,
             action_url, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            notification_id,
            dedupe_key.strip(),
            category.strip(),
            severity,
            title.strip(),
            message.strip(),
            json.dumps(details or {}, ensure_ascii=False),
            action_url,
            created_at or utc_now(),
        ),
    )
    if cursor.rowcount:
        from .admin_notification_delivery import (
            enqueue_configured_admin_deliveries,
        )

        enqueue_configured_admin_deliveries(
            conn,
            notification_id=notification_id,
            category=category.strip(),
            severity=severity,
            title=title.strip(),
            message=message.strip(),
            action_url=action_url,
            created_at=created_at or utc_now(),
        )
        return notification_id, True
    row = conn.execute(
        "SELECT id FROM admin_notifications WHERE dedupe_key = ?",
        (dedupe_key.strip(),),
    ).fetchone()
    return str(row["id"] if isinstance(row, sqlite3.Row) else row[0]), False


def list_notifications(
    conn: sqlite3.Connection,
    *,
    unread_only: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    limit = max(1, min(int(limit), 200))
    where = "WHERE read_at IS NULL" if unread_only else ""
    rows = conn.execute(
        f"SELECT * FROM admin_notifications {where} ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    unread = int(
        conn.execute(
            "SELECT COUNT(*) FROM admin_notifications WHERE read_at IS NULL"
        ).fetchone()[0]
    )
    items = []
    for row in rows:
        item = dict(row)
        item["details"] = json.loads(item.pop("details_json") or "{}")
        items.append(item)
    return {"items": items, "unread": unread}


def mark_notifications_read(
    conn: sqlite3.Connection,
    notification_ids: Iterable[str] | None = None,
    *,
    read_at: str | None = None,
) -> int:
    ids = [str(value) for value in (notification_ids or []) if str(value).strip()]
    timestamp = read_at or utc_now()
    if not ids:
        cursor = conn.execute(
            "UPDATE admin_notifications SET read_at = ? WHERE read_at IS NULL",
            (timestamp,),
        )
        return cursor.rowcount
    placeholders = ",".join("?" for _ in ids)
    cursor = conn.execute(
        f"UPDATE admin_notifications SET read_at = ? "
        f"WHERE read_at IS NULL AND id IN ({placeholders})",
        (timestamp, *ids),
    )
    return cursor.rowcount


def enqueue_social_deliveries(
    conn: sqlite3.Connection,
    *,
    publication_id: str,
    networks: Iterable[str],
    created_at: str | None = None,
) -> int:
    now = created_at or utc_now()
    inserted = 0
    for network in dict.fromkeys(str(value).strip().lower() for value in networks):
        if network not in SOCIAL_NETWORKS:
            raise ValueError("UNSUPPORTED_SOCIAL_NETWORK")
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO social_delivery_outbox
                (id, publication_id, network, next_attempt_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), publication_id, network, now, now),
        )
        inserted += cursor.rowcount
    return inserted


def enqueue_configured_social_deliveries(
    conn: sqlite3.Connection,
    publication_id: str,
) -> int:
    row = conn.execute(
        "SELECT value_json FROM admin_settings WHERE key = 'social_syndication'"
    ).fetchone()
    settings = json.loads(row["value_json"] or "{}") if row else {}
    if not settings.get("masterEnabled") or not settings.get("autoPublish"):
        return 0
    networks = settings.get("networks") if isinstance(settings.get("networks"), dict) else {}
    enabled = [
        name for name in SOCIAL_NETWORKS
        if (
            name == "vk_story"
            and bool((networks.get("vk") or {}).get("storyEnabled", False))
            and bool((networks.get("vk") or {}).get("verified", False))
        ) or (
            name != "vk_story"
            and bool((networks.get(name) or {}).get("enabled", False))
            and bool((networks.get(name) or {}).get("verified", False))
        )
    ]
    return enqueue_social_deliveries(
        conn, publication_id=publication_id, networks=enabled
    )


def openrouter_change_notification(
    conn: sqlite3.Connection,
    lifecycle: dict[str, Any],
) -> tuple[str, bool] | None:
    changes = lifecycle.get("changes") if isinstance(lifecycle, dict) else {}
    if not isinstance(changes, dict):
        return None
    counts: dict[str, int] = {}
    for kind in ("images", "videos"):
        row = changes.get(kind) if isinstance(changes.get(kind), dict) else {}
        for name in ("added", "removed", "priceChanged", "unpriced"):
            counts[f"{kind}.{name}"] = len(row.get(name) or [])
    meaningful = sum(
        value for key, value in counts.items() if not key.endswith(".unpriced")
    )
    if meaningful == 0:
        return None
    refreshed_at = str(lifecycle.get("refreshedAt") or utc_now())
    severity = "warning" if counts["images.removed"] + counts["videos.removed"] else "info"
    summary = (
        f"Новые: {counts['images.added'] + counts['videos.added']}; "
        f"удалены: {counts['images.removed'] + counts['videos.removed']}; "
        f"цена изменилась: {counts['images.priceChanged'] + counts['videos.priceChanged']}; "
        f"без цены: {counts['images.unpriced'] + counts['videos.unpriced']}."
    )
    return create_notification(
        conn,
        dedupe_key=f"openrouter-catalog:{refreshed_at}",
        category="openrouter_catalog",
        severity=severity,
        title="Изменения каталога OpenRouter",
        message=summary,
        details={"changes": changes, "refreshedAt": refreshed_at},
        action_url="/admin/openrouter",
        created_at=refreshed_at,
    )
