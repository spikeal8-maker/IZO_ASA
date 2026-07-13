"""Idempotent execution groups for the legacy SQLite initializer."""

from __future__ import annotations

import sqlite3

from .migrations import (
    FEED_PUBLICATION_ADDITIVE_COLUMNS,
    IMAGE_SOURCE_ADDITIVE_COLUMNS,
    add_missing_columns,
)
from .schema import IMAGE_SEARCH_SCHEMA_SQL


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
