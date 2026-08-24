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


ADMIN_NOTIFICATIONS_MIGRATION = MigrationDefinition(
    version=2,
    name="admin_notifications_and_social_outbox",
    checksum="sha256:117d2bec74e8cd7c20fddc339a715f2cb6b929f9489c5fb8f68be81baa4dd94b",
)


ADMIN_NOTIFICATION_DELIVERY_MIGRATION = MigrationDefinition(
    version=3,
    name="admin_notification_delivery_outbox",
    checksum="sha256:03fb62b844266d345247b1a1bbc9e4b048eefd7193c24456eb25bb1371f8597c",
)


ACCOUNT_VERIFICATION_MIGRATION = MigrationDefinition(
    version=4,
    name="social_account_verification",
    checksum="sha256:257bf268a45473725f865bea35ab1ad03a9911c7fdcb9bd1fd586a4ff675289f",
)


PHONE_CHAT_HISTORY_MIGRATION = MigrationDefinition(
    version=5,
    name="phone_chat_history",
    checksum="sha256:cb56d0bb48cb8062fdf7e2f71ca6a2ea62de880f48b347339729e324648f939e",
)


ADMIN_NOTIFICATIONS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS admin_notifications (
    id TEXT PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    action_url TEXT,
    created_at TEXT NOT NULL,
    read_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_admin_notifications_unread
    ON admin_notifications(read_at, created_at DESC);

CREATE TABLE IF NOT EXISTS social_delivery_outbox (
    id TEXT PRIMARY KEY,
    publication_id TEXT NOT NULL,
    network TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    external_id TEXT,
    external_url TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    UNIQUE(publication_id, network)
);
CREATE INDEX IF NOT EXISTS idx_social_delivery_outbox_pending
    ON social_delivery_outbox(status, next_attempt_at, created_at);
"""


ADMIN_NOTIFICATION_DELIVERY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS admin_notification_delivery_outbox (
    id TEXT PRIMARY KEY,
    notification_id TEXT NOT NULL,
    channel TEXT NOT NULL CHECK (channel IN ('telegram', 'email')),
    destination TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'retry', 'sent', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    external_id TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    UNIQUE(notification_id, channel, destination),
    FOREIGN KEY(notification_id) REFERENCES admin_notifications(id)
);
CREATE INDEX IF NOT EXISTS idx_admin_notification_delivery_pending
    ON admin_notification_delivery_outbox(status, next_attempt_at, created_at);
"""


ACCOUNT_VERIFICATION_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS account_verifications (
    internal_user_id TEXT PRIMARY KEY,
    verification_kind TEXT NOT NULL CHECK (verification_kind = 'social'),
    status TEXT NOT NULL CHECK (status IN ('pending', 'verified', 'deleted')),
    required_at TEXT NOT NULL,
    remind_after_at TEXT NOT NULL,
    delete_after_at TEXT NOT NULL,
    verified_at TEXT,
    verified_provider TEXT CHECK (verified_provider IN ('max', 'telegram')),
    provider_user_id TEXT,
    deleted_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_account_verifications_pending_delete
    ON account_verifications(status, delete_after_at);
"""


PHONE_CHAT_HISTORY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS phone_chat_threads (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    chat_model_id TEXT NOT NULL DEFAULT 'local:izo-chat',
    image_model_id TEXT,
    video_model_id TEXT,
    context_chars INTEGER NOT NULL DEFAULT 60000 CHECK (context_chars BETWEEN 4000 AND 240000),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_phone_chat_threads_user_updated
    ON phone_chat_threads(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS phone_chat_messages (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    tools_json TEXT NOT NULL DEFAULT '[]',
    charged_tokens INTEGER NOT NULL DEFAULT 0,
    token_kind TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(thread_id) REFERENCES phone_chat_threads(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_phone_chat_messages_thread_created
    ON phone_chat_messages(thread_id, created_at, id);
"""


def apply_admin_notifications_migration(
    conn: sqlite3.Connection,
    *,
    applied_at: str,
) -> bool:
    """Apply the additive notification/social-outbox schema exactly once."""

    conn.executescript(ADMIN_NOTIFICATIONS_SCHEMA_SQL)
    return record_applied_migration(
        conn,
        ADMIN_NOTIFICATIONS_MIGRATION,
        applied_at=applied_at,
    )


def apply_admin_notification_delivery_migration(
    conn: sqlite3.Connection,
    *,
    applied_at: str,
) -> bool:
    """Apply the additive durable administrator-delivery queue once."""

    conn.executescript(ADMIN_NOTIFICATION_DELIVERY_SCHEMA_SQL)
    return record_applied_migration(
        conn,
        ADMIN_NOTIFICATION_DELIVERY_MIGRATION,
        applied_at=applied_at,
    )


def apply_account_verification_migration(
    conn: sqlite3.Connection,
    *,
    applied_at: str,
) -> bool:
    """Apply the additive deferred social-verification state exactly once."""
    conn.executescript(ACCOUNT_VERIFICATION_SCHEMA_SQL)
    return record_applied_migration(
        conn,
        ACCOUNT_VERIFICATION_MIGRATION,
        applied_at=applied_at,
    )


def apply_phone_chat_history_migration(
    conn: sqlite3.Connection,
    *,
    applied_at: str,
) -> bool:
    """Apply durable per-user phone chat threads and messages exactly once."""
    conn.executescript(PHONE_CHAT_HISTORY_SCHEMA_SQL)
    return record_applied_migration(
        conn,
        PHONE_CHAT_HISTORY_MIGRATION,
        applied_at=applied_at,
    )


USER_EARLY_ADDITIVE_COLUMNS = {
    "plan": "TEXT NOT NULL DEFAULT 'mini'",
    "plan_expires_at": "TEXT",
    "plan_started_at": "TEXT",
    "plan_next_token_grant_at": "TEXT",
    "plan_monthly_token_grant": "INTEGER NOT NULL DEFAULT 0",
    "plan_term_months": "INTEGER NOT NULL DEFAULT 1",
    "plan_grant_source": "TEXT",
    "pending_plan_json": "TEXT",
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
    "personal_discount_percent": "INTEGER NOT NULL DEFAULT 0",
}

IMAGE_ADDITIVE_COLUMNS = {
    "deleted_at": "TEXT",
    "storage_tier": "TEXT NOT NULL DEFAULT 'original'",
    "optimized_at": "TEXT",
    "original_bytes": "INTEGER",
    "stored_bytes": "INTEGER",
}

FEED_PUBLICATION_ADDITIVE_COLUMNS = {
    "media_type": "TEXT NOT NULL DEFAULT 'image'",
    "video_id": "TEXT",
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
    "video_poster_name": "TEXT",
    "video_poster_width": "INTEGER",
    "video_poster_height": "INTEGER",
    "video_poster_bytes": "INTEGER",
    "video_preview_name": "TEXT",
    "video_preview_bytes": "INTEGER",
    "video_full_name": "TEXT",
    "video_full_bytes": "INTEGER",
    "duration_ms": "INTEGER",
    "has_audio": "INTEGER NOT NULL DEFAULT 0",
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


def rebuild_feed_publications_media_neutral(conn: sqlite3.Connection) -> bool:
    """Make image_id nullable while preserving every existing feed column and row."""
    columns = conn.execute("PRAGMA table_info(feed_publications)").fetchall()
    if not columns:
        return False
    image_column = next((row for row in columns if row["name"] == "image_id"), None)
    required = set(FEED_PUBLICATION_ADDITIVE_COLUMNS)
    names = {str(row["name"]) for row in columns}
    if image_column is not None and not bool(image_column["notnull"]) and required <= names:
        return False

    shadow = "feed_publications_v3_shadow"
    for name in names | {shadow}:
        if not _SQL_IDENTIFIER.fullmatch(name):
            raise ValueError(f"Unsafe SQLite identifier: {name!r}")

    definitions: list[str] = []
    for row in columns:
        name = str(row["name"])
        column_type = str(row["type"] or "TEXT")
        definition = f'"{name}" {column_type}'
        if bool(row["pk"]):
            definition += " PRIMARY KEY"
        elif name != "image_id" and bool(row["notnull"]):
            definition += " NOT NULL"
        if row["dflt_value"] is not None:
            definition += f" DEFAULT {row['dflt_value']}"
        definitions.append(definition)
    definitions.extend([
        "UNIQUE(image_id)",
        "UNIQUE(video_id)",
        "CHECK (media_type IN ('image', 'video'))",
        "CHECK ((media_type = 'image' AND image_id IS NOT NULL AND video_id IS NULL) "
        "OR (media_type = 'video' AND video_id IS NOT NULL AND image_id IS NULL))",
    ])
    quoted_columns = ", ".join(f'"{str(row["name"])}"' for row in columns)
    before = [
        tuple(row)
        for row in conn.execute(
            f"SELECT {quoted_columns} FROM feed_publications ORDER BY id"
        ).fetchall()
    ]

    conn.execute("SAVEPOINT feed_publications_media_neutral")
    try:
        conn.execute(f"DROP TABLE IF EXISTS {shadow}")
        conn.execute(f"CREATE TABLE {shadow} ({', '.join(definitions)})")
        conn.execute(
            f"INSERT INTO {shadow} ({quoted_columns}) "
            f"SELECT {quoted_columns} FROM feed_publications"
        )
        after = [
            tuple(row)
            for row in conn.execute(
                f"SELECT {quoted_columns} FROM {shadow} ORDER BY id"
            ).fetchall()
        ]
        if before != after:
            raise RuntimeError("FEED_MEDIA_NEUTRAL_COPY_AUDIT_FAILED")
        conn.execute("DROP TABLE feed_publications")
        conn.execute(f"ALTER TABLE {shadow} RENAME TO feed_publications")
        conn.execute("RELEASE SAVEPOINT feed_publications_media_neutral")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT feed_publications_media_neutral")
        conn.execute("RELEASE SAVEPOINT feed_publications_media_neutral")
        raise
    return True


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
    ledger_exists = conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    existing = (
        conn.execute(
            "SELECT name, checksum FROM schema_migrations WHERE version = ?",
            (migration.version,),
        ).fetchone()
        if ledger_exists
        else None
    )
    if existing is not None:
        if existing["name"] != migration.name or existing["checksum"] != migration.checksum:
            raise RuntimeError("MIGRATION_DEFINITION_MISMATCH")
        if sqlite_user_version(conn) < migration.version:
            conn.execute(f"PRAGMA user_version = {migration.version}")
        return False

    ensure_migration_ledger(conn, supported_version=migration.version)
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
    if sqlite_user_version(conn) > LEGACY_BASELINE_MIGRATION.version:
        existing = conn.execute(
            "SELECT name, checksum FROM schema_migrations WHERE version = ?",
            (LEGACY_BASELINE_MIGRATION.version,),
        ).fetchone()
        if existing is None:
            raise RuntimeError("LEGACY_BASELINE_MISSING")
        if (
            existing["name"] != LEGACY_BASELINE_MIGRATION.name
            or existing["checksum"] != LEGACY_BASELINE_MIGRATION.checksum
        ):
            raise RuntimeError("MIGRATION_DEFINITION_MISMATCH")
        return False
    return record_applied_migration(
        conn,
        LEGACY_BASELINE_MIGRATION,
        applied_at=applied_at,
    )
