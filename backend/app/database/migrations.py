"""Reusable primitives and declarations for additive SQLite migrations.

Only application-owned table and column identifiers may be passed here. The
helper validates identifiers before constructing SQLite ALTER statements.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping


USER_EARLY_ADDITIVE_COLUMNS = {
    "plan": "TEXT NOT NULL DEFAULT 'mini'",
    "token_balance": "INTEGER NOT NULL DEFAULT 50",
    "gallery_enabled": "INTEGER NOT NULL DEFAULT 1",
    "phone": "TEXT",
    "email": "TEXT",
    "middle_name": "TEXT",
    "country": "TEXT",
    "city": "TEXT",
    "timezone": "TEXT",
    "ref_code": "TEXT",
    "last_user_agent": "TEXT",
    "last_screen": "TEXT",
    "last_seen_at": "TEXT",
    "total_time_seconds": "INTEGER NOT NULL DEFAULT 0",
    "generation_count": "INTEGER NOT NULL DEFAULT 0",
    "tokens_used": "INTEGER NOT NULL DEFAULT 0",
    "promo_used_count": "INTEGER NOT NULL DEFAULT 0",
    "referrals_count": "INTEGER NOT NULL DEFAULT 0",
    "banned": "INTEGER NOT NULL DEFAULT 0",
    "display_name": "TEXT",
    "email_verified_at": "TEXT",
    "phone_verified_at": "TEXT",
    "public_user_code": "TEXT",
    "avatar_url": "TEXT",
    "avatar_preset": "TEXT",
    "public_about": "TEXT",
    "public_website": "TEXT",
    "public_focus": "TEXT",
    "public_phone": "TEXT",
    "public_links_json": "TEXT",
    "gender": "TEXT",
    "age": "INTEGER",
    "daily_tokens_used": "INTEGER NOT NULL DEFAULT 0",
    "last_daily_reset": "TEXT",
    "openrouter_monthly_tokens_used": "INTEGER NOT NULL DEFAULT 0",
    "last_openrouter_month_reset": "TEXT",
}

IMAGE_ADDITIVE_COLUMNS = {
    "deleted_at": "TEXT",
    "storage_tier": "TEXT NOT NULL DEFAULT 'original'",
    "optimized_at": "TEXT",
    "original_bytes": "INTEGER",
    "stored_bytes": "INTEGER",
}

FEED_PUBLICATION_ADDITIVE_COLUMNS = {
    "feed_thumb_name": "TEXT",
    "feed_large_name": "TEXT",
    "feed_thumb_width": "INTEGER",
    "feed_thumb_height": "INTEGER",
    "feed_thumb_bytes": "INTEGER",
    "feed_large_width": "INTEGER",
    "feed_large_height": "INTEGER",
    "feed_large_bytes": "INTEGER",
    "media_ready_at": "TEXT",
    "media_error": "TEXT",
    "native_aspect_ratio": "TEXT",
    "orientation": "TEXT",
    "source_type": "TEXT",
    "source_label": "TEXT",
    "display_policy": "TEXT",
    "category": "TEXT",
    "remix_policy": "TEXT",
    "tags_json": "TEXT",
    "generation_snapshot_json": "TEXT",
    "updated_at": "TEXT",
    "view_count": "INTEGER NOT NULL DEFAULT 0",
}

IMAGE_SOURCE_ADDITIVE_COLUMNS = {
    "children_json": "TEXT NOT NULL DEFAULT '[]'",
    "is_favorite": "INTEGER NOT NULL DEFAULT 0",
    "library_deleted_at": "TEXT",
    "availability_status": "TEXT NOT NULL DEFAULT 'unknown'",
    "availability_checked_at": "TEXT",
    "unavailable_at": "TEXT",
}

_SQL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _SQL_IDENTIFIER.fullmatch(table):
        raise ValueError(f"Unsafe SQLite table identifier: {table!r}")
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def add_missing_columns(
    conn: sqlite3.Connection,
    table: str,
    columns: Mapping[str, str],
) -> list[str]:
    """Apply additive columns in declaration order and report what was added."""
    existing = table_columns(conn, table)
    added: list[str] = []
    for column, definition in columns.items():
        if not _SQL_IDENTIFIER.fullmatch(column):
            raise ValueError(f"Unsafe SQLite column identifier: {column!r}")
        if column in existing:
            continue
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        existing.add(column)
        added.append(column)
    return added
