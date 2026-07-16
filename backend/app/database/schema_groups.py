"""Idempotent execution groups for the legacy SQLite initializer."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable

from .migrations import (
    FEED_PUBLICATION_ADDITIVE_COLUMNS,
    IMAGE_ADDITIVE_COLUMNS,
    IMAGE_SOURCE_ADDITIVE_COLUMNS,
    USER_EARLY_ADDITIVE_COLUMNS,
    add_missing_columns,
)
from .schema import BASE_SCHEMA_SQL, IDENTITY_SCHEMA_SQL, IMAGE_SEARCH_SCHEMA_SQL


PublicUserCodeAssigner = Callable[[sqlite3.Connection, str], str | None]


def prepare_core_schema_group(conn: sqlite3.Connection) -> None:
    """Create the base schema and its early additive user/image columns."""
    conn.executescript(BASE_SCHEMA_SQL)
    add_missing_columns(conn, "users", USER_EARLY_ADDITIVE_COLUMNS)
    add_missing_columns(conn, "images", IMAGE_ADDITIVE_COLUMNS)


def seed_core_defaults(conn: sqlite3.Connection, *, now: str) -> None:
    """Seed the stable demo user, model profiles and system presets."""
    conn.execute(
        """
        INSERT OR IGNORE INTO users (id, username, first_name, language, role, created_at, last_login_at)
        VALUES ('demo_user', 'demo', 'Demo', 'ru', 'admin', ?, ?)
        """,
        (now, now),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO model_profiles (id, name, provider, model_name)
        VALUES ('local_flux_klein', 'Local Flux Klein', 'comfyui', 'flux-2-klein-9b-fp8.safetensors')
        """
    )
    add_missing_columns(conn, "model_profiles", {"supports_pose": "INTEGER NOT NULL DEFAULT 0"})
    seed_profiles = [
        (
            "flux_klein_4b",
            "FLUX.2 [klein] 4B",
            "flux-2-klein-4b-fp8.safetensors",
            0,
            {
                "variant": "4b",
                "unet": "flux-2-klein-4b-fp8.safetensors",
                "text_encoder": "qwen_3_4b",
                "vae": "flux2-vae.safetensors",
                "faceswap_lora": "bfs_head_v1_flux-klein_4b",
                "node": "FluxKleinOneNode",
                "pose": {
                    "supported": False,
                    "reason": "repo refcontrol pose LoRA is published for 9B only",
                },
            },
        ),
        (
            "flux_klein_9b",
            "FLUX.2 [klein] 9B",
            "flux-2-klein-9b-fp8.safetensors",
            1,
            {
                "variant": "9b",
                "unet": "flux-2-klein-9b-fp8.safetensors",
                "text_encoder": "qwen_3_8b",
                "vae": "flux2-vae.safetensors",
                "faceswap_lora": "bfs_head_v1_flux-klein_9b",
                "node": "FluxKleinOneNode",
                "pose": {
                    "supported": True,
                    "lora": "refcontrol_v2_poses.safetensors",
                    "preprocessor_node": "DWPreprocessor",
                    "workflow": "pose",
                },
            },
        ),
    ]
    for profile_id, name, model_name, supports_pose, settings in seed_profiles:
        conn.execute(
            """
            INSERT OR IGNORE INTO model_profiles
                (id, name, provider, model_name, supports_pose, settings_json)
            VALUES (?, ?, 'comfyui', ?, ?, ?)
            """,
            (
                profile_id,
                name,
                model_name,
                supports_pose,
                json.dumps(settings, ensure_ascii=False),
            ),
        )
    seed_presets = [
        ("portrait", "Кинематографичный портрет", "Cinematic portrait", "text_to_image"),
        ("enhance", "Улучшить качество", "Enhance quality", "edit"),
        ("collage", "Коллаж в сцену", "Collage to scene", "paint"),
    ]
    for preset_id, name_ru, name_en, mode in seed_presets:
        conn.execute(
            """
            INSERT OR IGNORE INTO presets (id, name_ru, name_en, mode, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (preset_id, name_ru, name_en, mode, now, now),
        )
    for sort_order, code, name, tokens, price in (
        (10, "tokens_50", "50 токенов", 50, 250),
        (20, "tokens_100", "100 токенов", 100, 500),
        (30, "tokens_250", "250 токенов", 250, 1250),
    ):
        conn.execute(
            """
            INSERT OR IGNORE INTO billing_packages
                (id, code, name, description, price_amount, currency, token_amount, is_active, sort_order, created_at, updated_at)
            VALUES (?, ?, ?, 'Дополнительные токены для премиум-моделей', ?, 'RUB', ?, 1, ?, ?, ?)
            """,
            (uuid.uuid4().hex, code, name, price, tokens, sort_order, now, now),
        )
    for sort_order, code, name, price in (
        (110, "tariff_mini", "Тариф Mini на 30 дней", 490),
        (120, "tariff_plus", "Тариф Plus на 30 дней", 990),
        (130, "tariff_pro", "Тариф Pro на 30 дней", 1990),
        (140, "tariff_business", "Тариф Бизнес на 30 дней", 4990),
    ):
        conn.execute(
            """
            INSERT OR IGNORE INTO billing_packages
                (id, code, name, description, price_amount, currency, token_amount, is_active, sort_order, created_at, updated_at)
            VALUES (?, ?, ?, 'Подписка ИЗО АСА на 30 дней', ?, 'RUB', 0, 1, ?, ?, ?)
            """,
            (uuid.uuid4().hex, code, name, price, sort_order, now, now),
        )


def seed_default_challenge(conn: sqlite3.Connection, *, now: str) -> None:
    """Seed the stable launch challenge after its Identity schema table exists."""
    conn.execute(
        """
        INSERT OR IGNORE INTO challenges (
            id, title, description, rules, prompt_hint, category, status,
            reward_pool, starts_at, ends_at, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
        """,
        (
            "moscow_2120_week",
            "Москва 2120",
            "Покажите город будущего. Лучшие работы получают токены и место в витрине.",
            "Создайте образ Москвы будущего: город, транспорт, люди, архитектура или повседневная сцена. Без логотипов, текста на изображении и копирования чужих работ.",
            "Футуристическая Москва 2120 года, город будущего, выразительная архитектура, живые люди, кинематографичный свет",
            "challenge_moscow_2120",
            10000,
            "2026-07-01T00:00:00+00:00",
            "2026-07-14T23:59:59+00:00",
            now,
        ),
    )


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
        "CREATE INDEX IF NOT EXISTS idx_feed_publications_moderation_created "
        "ON feed_publications(moderation_status, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_feed_reactions_viewer_kind "
        "ON feed_reactions(internal_user_id, kind, publication_id)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS feed_view_events ("
        "publication_id TEXT NOT NULL, viewer_key TEXT NOT NULL, "
        "first_viewed_at TEXT NOT NULL, last_viewed_at TEXT NOT NULL, "
        "accepted_view_count INTEGER NOT NULL DEFAULT 1, "
        "PRIMARY KEY (publication_id, viewer_key))"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_feed_view_events_viewer_recent "
        "ON feed_view_events(viewer_key, last_viewed_at DESC, publication_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_feed_view_events_last_viewed "
        "ON feed_view_events(last_viewed_at)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS feed_subscription_reads ("
        "internal_user_id TEXT PRIMARY KEY, last_read_at TEXT NOT NULL)"
    )
    conn.execute(
        "UPDATE feed_publications SET metric_origin = 'editorial_seed' "
        "WHERE metric_origin = 'organic' "
        "AND (internal_user_id LIKE 'seed_author_%' OR id LIKE 'seed-pub-%')"
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
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_videos_active_user_created "
        "ON videos(user_id, created_at DESC, id DESC) WHERE deleted_at IS NULL"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_videos_job_id "
        "ON videos(job_id)"
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
