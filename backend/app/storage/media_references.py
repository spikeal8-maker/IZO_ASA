"""Exact owner-scoped media reference queries."""

from __future__ import annotations

import sqlite3


def _query_pattern(prefix: str) -> str:
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}?%"


def exact_media_url_params(filename: str) -> tuple[str, str, str, str]:
    canonical = f"/api/media/{filename}"
    legacy = f"/media/{filename}"
    return canonical, _query_pattern(canonical), legacy, _query_pattern(legacy)


def find_owned_active_image(
    conn: sqlite3.Connection,
    filename: str,
    user_id: str,
    *,
    active_image_where: str,
):
    canonical, canonical_query, legacy, legacy_query = exact_media_url_params(filename)
    return conn.execute(
        f"""
        SELECT id, user_id, url, thumbnail_url FROM images
        WHERE user_id = ? AND {active_image_where}
          AND (
            url = ? OR url LIKE ? ESCAPE '\\'
            OR thumbnail_url = ? OR thumbnail_url LIKE ? ESCAPE '\\'
            OR url = ? OR url LIKE ? ESCAPE '\\'
            OR thumbnail_url = ? OR thumbnail_url LIKE ? ESCAPE '\\'
          )
        LIMIT 1
        """,
        (
            user_id,
            canonical,
            canonical_query,
            canonical,
            canonical_query,
            legacy,
            legacy_query,
            legacy,
            legacy_query,
        ),
    ).fetchone()


def owned_active_source_exists(
    conn: sqlite3.Connection,
    filename: str,
    user_id: str,
    *,
    active_image_where: str,
) -> bool:
    canonical, canonical_query, legacy, legacy_query = exact_media_url_params(filename)
    row = conn.execute(
        f"""
        SELECT 1 FROM image_sources s
        JOIN images i ON i.id = s.image_id AND i.user_id = s.user_id
        WHERE s.user_id = ?
          AND (s.library_deleted_at IS NULL OR s.library_deleted_at = '')
          AND {active_image_where.replace('deleted_at', 'i.deleted_at')}
          AND (
            s.thumb_url = ? OR s.thumb_url LIKE ? ESCAPE '\\'
            OR s.thumb_url = ? OR s.thumb_url LIKE ? ESCAPE '\\'
          )
        LIMIT 1
        """,
        (user_id, canonical, canonical_query, legacy, legacy_query),
    ).fetchone()
    return row is not None


def owned_job_media_reference_exists(
    conn: sqlite3.Connection,
    filename: str,
    user_id: str,
) -> bool:
    canonical, canonical_query, legacy, legacy_query = exact_media_url_params(filename)
    row = conn.execute(
        """
        SELECT 1 FROM jobs j
        WHERE j.user_id = ?
          AND EXISTS (
            SELECT 1
            FROM json_tree(
              CASE WHEN json_valid(j.settings_json) THEN j.settings_json ELSE '{}' END
            ) AS value
            WHERE value.type = 'text'
              AND (
                value.value = ? OR value.value LIKE ? ESCAPE '\\'
                OR value.value = ? OR value.value LIKE ? ESCAPE '\\'
              )
          )
        LIMIT 1
        """,
        (user_id, canonical, canonical_query, legacy, legacy_query),
    ).fetchone()
    return row is not None
