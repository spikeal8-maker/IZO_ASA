"""Reusable primitives and declarations for additive SQLite migrations.

Only application-owned table and column identifiers may be passed here. The
helper validates identifiers before constructing SQLite ALTER statements.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass


MIGRATION_LEDGER_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY CHECK (version > 0),
    name TEXT NOT NULL UNIQUE,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
)
"""


@dataclass(frozen=True)
class MigrationDefinition:
    version: int
    name: str
    checksum: str

    def __post_init__(self) -> None:
        if self.version <= 0:
            raise ValueError("Migration version must be positive.")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_]*", self.name):
            raise ValueError("Migration name must use lowercase ASCII identifiers.")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.checksum):
            raise ValueError("Migration checksum must be a lowercase SHA-256 value.")


LEGACY_BASELINE_MIGRATION = MigrationDefinition(
    version=1,
    name="legacy_schema_baseline",
    checksum="sha256:ed687bd48f5f07c01f445e184a5939782b112d7af6a91b99fe825791b29038a5",
)


USER_EARLY_ADDITIVE_COLUMNS = {
    "plan": "TEXT NOT NULL DEFAULT 'mini'",
    "plan_expires_at": "TEXT",
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
    "moderation_status": "TEXT NOT NULL DEFAULT 'approved'",
    "moderation_reason": "TEXT",
    "moderated_at": "TEXT",
    "moderated_by_internal_user_id": "TEXT",
    "source_job_id": "TEXT",
    "metric_origin": "TEXT NOT NULL DEFAULT 'organic'",
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


def sqlite_user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def ensure_migration_ledger(
    conn: sqlite3.Connection,
    *,
    supported_version: int,
) -> None:
    current_version = sqlite_user_version(conn)
    if current_version > supported_version:
        raise RuntimeError("DATABASE_SCHEMA_VERSION_UNSUPPORTED")
    conn.execute(MIGRATION_LEDGER_SQL)
    row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    ledger_version = int(row[0] or 0)
    if ledger_version > supported_version:
        raise RuntimeError("MIGRATION_LEDGER_VERSION_UNSUPPORTED")


def record_applied_migration(
    conn: sqlite3.Connection,
    migration: MigrationDefinition,
    *,
    applied_at: str,
) -> bool:
    ensure_migration_ledger(conn, supported_version=migration.version)
    existing = conn.execute(
        "SELECT name, checksum FROM schema_migrations WHERE version = ?",
        (migration.version,),
    ).fetchone()
    if existing is not None:
        if existing["name"] != migration.name or existing["checksum"] != migration.checksum:
            raise RuntimeError("MIGRATION_DEFINITION_MISMATCH")
        if sqlite_user_version(conn) < migration.version:
            conn.execute(f"PRAGMA user_version = {migration.version}")
        return False

    reused_name = conn.execute(
        "SELECT version FROM schema_migrations WHERE name = ?",
        (migration.name,),
    ).fetchone()
    if reused_name is not None:
        raise RuntimeError("MIGRATION_NAME_REUSED")
    conn.execute(
        "INSERT INTO schema_migrations (version, name, checksum, applied_at) VALUES (?, ?, ?, ?)",
        (migration.version, migration.name, migration.checksum, applied_at),
    )
    conn.execute(f"PRAGMA user_version = {migration.version}")
    return True


def finalize_legacy_schema_baseline(
    conn: sqlite3.Connection,
    *,
    applied_at: str,
) -> bool:
    return record_applied_migration(
        conn,
        LEGACY_BASELINE_MIGRATION,
        applied_at=applied_at,
    )
