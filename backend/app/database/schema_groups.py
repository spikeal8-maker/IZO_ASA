"""Idempotent execution groups for the legacy SQLite initializer."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable

from .migrations import (
    FEED_PUBLICATION_ADDITIVE_COLUMNS,
    IMAGE_SOURCE_ADDITIVE_COLUMNS,
    add_missing_columns,
)
from .schema import IDENTITY_SCHEMA_SQL, IMAGE_SEARCH_SCHEMA_SQL


PublicUserCodeAssigner = Callable[[sqlite3.Connection, str], str | None]


def prepare_identity_schema_group(conn: sqlite3.Connection, *, now: str) -> None:
    """Create additive Identity Core schema before dependent schema groups run."""
    add_missing_columns(conn, "users", {"internal_user_id": "TEXT"})
    conn.execute(
        """
        INSERT OR IGNORE INTO users (
            id, username, first_name, display_name, language, role, plan,
            token_balance, gallery_enabled, internal_user_id, created_at, last_login_at
        )
        VALUES (
            'seed_editorial', 'seed_editorial', 'Выбор редакции', 'Выбор редакции',
            'ru', 'user', 'mini', 0, 0, 'seed_editorial', ?, ?
        )
        """,
        (now, now),
    )
    conn.executescript(IDENTITY_SCHEMA_SQL)
    add_missing_columns(conn, "auth_sessions", {"refresh_expires_at": "TEXT"})


def backfill_identity_core(conn: sqlite3.Connection, now: str) -> None:
    """Backfill canonical IDs and legacy Telegram/MAX identities idempotently."""
    for row in conn.execute("SELECT id FROM users WHERE internal_user_id IS NULL").fetchall():
        conn.execute(
            "UPDATE users SET internal_user_id = ? WHERE id = ? AND internal_user_id IS NULL",
            (uuid.uuid4().hex, row["id"]),
        )

    user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    for provider, column in (("telegram", "telegram_id"), ("max", "max_id")):
        if column not in user_columns:
            continue
        duplicates = conn.execute(
            f"SELECT {column} AS pid, COUNT(*) AS c FROM users "
            f"WHERE {column} IS NOT NULL AND {column} <> '' "
            f"GROUP BY {column} HAVING c > 1"
        ).fetchall()
        if duplicates:
            raise RuntimeError(
                f"Duplicate {column} values detected across distinct users "
                f"({[row['pid'] for row in duplicates]}); refusing to backfill "
                "auth_identities to avoid silently merging users."
            )
        for row in conn.execute(
            f"SELECT id, internal_user_id, {column} AS pid FROM users "
            f"WHERE {column} IS NOT NULL AND {column} <> ''"
        ).fetchall():
            conn.execute(
                """
                INSERT OR IGNORE INTO auth_identities
                    (id, internal_user_id, legacy_user_id, provider, provider_user_id, linked_at, verified_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    uuid.uuid4().hex,
                    row["internal_user_id"],
                    row["id"],
                    provider,
                    str(row["pid"]),
                    now,
                ),
            )


def finalize_identity_schema_group(
    conn: sqlite3.Connection,
    *,
    now: str,
    ensure_public_user_code: PublicUserCodeAssigner,
) -> None:
    """Backfill Identity Core, then enforce canonical/public-code uniqueness."""
    backfill_identity_core(conn, now)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_users_internal_user_id "
        "ON users(internal_user_id) WHERE internal_user_id IS NOT NULL"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_users_public_user_code "
        "ON users(public_user_code) WHERE public_user_code IS NOT NULL"
    )
    for row in conn.execute(
        "SELECT internal_user_id FROM users "
        "WHERE public_user_code IS NULL AND internal_user_id IS NOT NULL"
    ).fetchall():
        ensure_public_user_code(conn, row["internal_user_id"])


def initialize_media_schema_group(conn: sqlite3.Connection) -> None:
    """Apply feed, gallery search, image-source and job indexing schema."""
    add_missing_columns(conn, "feed_publications", FEED_PUBLICATION_ADDITIVE_COLUMNS)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_feed_publications_media_ready "
        "ON feed_publications(status, media_ready_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_feed_publications_category_ready_created "
        "ON feed_publications(category, status, media_ready_at, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_feed_publications_legacy_ready_created "
        "ON feed_publications(legacy_user_id, status, media_ready_at, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_images_user_deleted_created "
        "ON images(user_id, deleted_at, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_images_user_favorite_deleted_created "
        "ON images(user_id, is_favorite, deleted_at, created_at)"
    )
    conn.execute("UPDATE images SET deleted_at = NULL WHERE deleted_at = ''")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_images_active_user_created "
        "ON images(user_id, created_at DESC, id DESC) WHERE deleted_at IS NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_images_job_id "
        "ON images(job_id)"
    )
    conn.executescript(IMAGE_SEARCH_SCHEMA_SQL)
    conn.execute(
        """
        INSERT INTO images_search(rowid, image_id, user_id, search_text)
        SELECT images.rowid, images.id, images.user_id,
               COALESCE(images.id, '') || ' ' || COALESCE(images.prompt_original, '') || ' ' ||
               COALESCE(images.prompt_translated, '') || ' ' || COALESCE(images.mode, '') || ' ' ||
               COALESCE(images.provider, '') || ' ' || COALESCE(images.settings_json, '')
        FROM images
        WHERE NOT EXISTS (SELECT 1 FROM images_search WHERE images_search.rowid = images.rowid)
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_image_sources_image "
        "ON image_sources(image_id, slot_index)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_image_sources_user "
        "ON image_sources(user_id, created_at)"
    )
    add_missing_columns(conn, "image_sources", IMAGE_SOURCE_ADDITIVE_COLUMNS)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_image_sources_library_available "
        "ON image_sources(user_id, availability_status, created_at DESC) "
        "WHERE library_deleted_at IS NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_user_created "
        "ON jobs(user_id, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_result_image "
        "ON jobs(result_image_id)"
    )
