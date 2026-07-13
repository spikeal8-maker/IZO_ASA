"""Unit contracts for import-safe SQLite connection and DB Guard modules."""

from __future__ import annotations

import json
import sqlite3

import pytest

import main

from app.database import (
    BASE_SCHEMA_SQL,
    IDENTITY_SCHEMA_SQL,
    IMAGE_ADDITIVE_COLUMNS,
    IMAGE_SEARCH_SCHEMA_SQL,
    LEGACY_BASELINE_MIGRATION,
    MigrationDefinition,
    USER_EARLY_ADDITIVE_COLUMNS,
    DbGuardError,
    add_missing_columns,
    collect_sqlite_guard_status,
    open_sqlite,
    parse_allowed_database_paths,
    preflight_sqlite_database,
    ensure_migration_ledger,
    finalize_legacy_schema_baseline,
    finalize_identity_schema_group,
    initialize_media_schema_group,
    prepare_core_schema_group,
    prepare_identity_schema_group,
    record_applied_migration,
    safe_guard_payload,
    seed_core_defaults,
    seed_default_challenge,
    sqlite_user_version,
    table_columns,
)


def test_open_sqlite_applies_connection_policy(tmp_path):
    path = tmp_path / "policy.sqlite3"
    with open_sqlite(path) as conn:
        assert conn.row_factory is sqlite3.Row
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 10_000
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() in {"wal", "memory"}


def test_allowed_paths_accept_plain_and_sqlite_urls(tmp_path):
    first = tmp_path / "first.sqlite3"
    second = tmp_path / "second.sqlite3"
    parsed = parse_allowed_database_paths(f"{first};sqlite:///{second}")
    assert parsed == {first.resolve(), second.resolve()}


def test_production_preflight_rejects_missing_database_url(tmp_path):
    with pytest.raises(DbGuardError, match="DATABASE_URL is required"):
        preflight_sqlite_database(
            production_like=True,
            database_url="",
            path=tmp_path / "missing.sqlite3",
            allowed_paths=set(),
            min_size_mb=0,
        )


def test_guard_reports_schema_and_counts_without_fastapi(tmp_path):
    path = tmp_path / "guard.sqlite3"
    with open_sqlite(path) as conn:
        conn.executescript(
            """
            CREATE TABLE users (id TEXT, role TEXT, banned INTEGER);
            CREATE TABLE images (id TEXT);
            INSERT INTO users VALUES ('admin', 'admin', 0);
            """
        )

    status = collect_sqlite_guard_status(
        path=path,
        connection_factory=lambda: open_sqlite(path),
        required_tables={"users", "images"},
        required_columns={"users": {"id", "role", "banned"}},
        production_like=True,
        min_users=1,
        min_active_admins=1,
    )
    assert status["ok"] is True
    assert status["users_count"] == 1
    assert status["active_admin_count"] == 1


def test_safe_guard_payload_removes_details_and_normalizes_reason():
    payload = safe_guard_payload(
        {
            "ok": False,
            "status": "fail",
            "reason": "first\nsecond",
            "migration_status": "fail",
            "db_path": "C:/secret/live.sqlite3",
            "users_count": 100,
        }
    )
    assert payload == {
        "ok": False,
        "status": "fail",
        "reason": "first second",
        "migration_status": "fail",
    }


def test_add_missing_columns_is_ordered_and_idempotent(tmp_path):
    path = tmp_path / "migration.sqlite3"
    with open_sqlite(path) as conn:
        conn.execute("CREATE TABLE sample (id TEXT PRIMARY KEY)")
        columns = {"title": "TEXT", "enabled": "INTEGER NOT NULL DEFAULT 1"}
        assert add_missing_columns(conn, "sample", columns) == ["title", "enabled"]
        assert add_missing_columns(conn, "sample", columns) == []
        assert table_columns(conn, "sample") == {"id", "title", "enabled"}
        row = conn.execute("INSERT INTO sample (id) VALUES ('one') RETURNING enabled").fetchone()
        assert row["enabled"] == 1


def test_add_missing_columns_rejects_unsafe_identifiers(tmp_path):
    path = tmp_path / "unsafe.sqlite3"
    with open_sqlite(path) as conn:
        conn.execute("CREATE TABLE sample (id TEXT)")
        with pytest.raises(ValueError, match="Unsafe SQLite table identifier"):
            add_missing_columns(conn, "sample; DROP TABLE sample", {"title": "TEXT"})
        with pytest.raises(ValueError, match="Unsafe SQLite column identifier"):
            add_missing_columns(conn, "sample", {"title; DROP TABLE sample": "TEXT"})
        assert table_columns(conn, "sample") == {"id"}


def test_base_schema_is_idempotent_and_creates_core_tables(tmp_path):
    path = tmp_path / "base-schema.sqlite3"
    with open_sqlite(path) as conn:
        conn.executescript(BASE_SCHEMA_SQL)
        conn.executescript(BASE_SCHEMA_SQL)
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    assert {
        "users",
        "jobs",
        "images",
        "image_sources",
        "token_ledger",
        "billing_packages",
        "invoices",
        "payments",
        "refunds",
        "referral_rewards",
    } <= tables


def test_identity_schema_is_idempotent_and_creates_auth_feed_tables(tmp_path):
    path = tmp_path / "identity-schema.sqlite3"
    with open_sqlite(path) as conn:
        conn.executescript(BASE_SCHEMA_SQL)
        add_missing_columns(conn, "users", {"internal_user_id": "TEXT"})
        conn.executescript(IDENTITY_SCHEMA_SQL)
        conn.executescript(IDENTITY_SCHEMA_SQL)
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    assert {
        "auth_identities",
        "auth_sessions",
        "auth_passwords",
        "auth_otp_challenges",
        "session_events",
        "security_events",
        "audit_logs",
        "event_logs",
        "feed_publications",
        "feed_reactions",
        "challenges",
    } <= tables


def test_image_search_schema_is_idempotent_and_tracks_image_rows(tmp_path):
    path = tmp_path / "image-search-schema.sqlite3"
    with open_sqlite(path) as conn:
        conn.executescript(BASE_SCHEMA_SQL)
        conn.executescript(IMAGE_SEARCH_SCHEMA_SQL)
        conn.executescript(IMAGE_SEARCH_SCHEMA_SQL)
        conn.execute(
            """
            INSERT INTO images (
                id, user_id, job_id, url, thumbnail_url, prompt_original,
                prompt_translated, width, height, mode, provider, created_at
            ) VALUES (
                'img-search', 'user-search', 'job-search', '/api/media/a.png',
                '/api/media/a.webp', 'красный замок', 'red castle',
                704, 704, 'text_to_image', 'comfyui', '2026-01-01'
            )
            """
        )
        row = conn.execute(
            "SELECT image_id, user_id, search_text FROM images_search WHERE image_id = 'img-search'"
        ).fetchone()
    assert row["user_id"] == "user-search"
    assert "красный замок" in row["search_text"]
    assert "red castle" in row["search_text"]


def test_init_db_characterizes_media_schema_group_and_is_idempotent(tmp_path, monkeypatch):
    path = tmp_path / "media-schema-group.sqlite3"
    with open_sqlite(path) as conn:
        conn.executescript(BASE_SCHEMA_SQL)
        conn.execute(
            """
            INSERT INTO images (
                id, user_id, job_id, url, thumbnail_url, prompt_original,
                prompt_translated, width, height, mode, provider, created_at
            ) VALUES (
                'img-before-group', 'user-media', 'job-media', '/api/media/before.png',
                '/api/media/before.webp', 'синий город', 'blue city',
                704, 704, 'text_to_image', 'comfyui', '2026-01-01'
            )
            """
        )
    monkeypatch.setattr(main, "DB_PATH", path)

    main.init_db()
    with open_sqlite(path) as conn:
        conn.execute("UPDATE images SET deleted_at = '' WHERE id = 'img-before-group'")
    main.init_db()

    with open_sqlite(path) as conn:
        indexes = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        search_rows = conn.execute(
            "SELECT image_id, user_id, search_text FROM images_search "
            "WHERE image_id = 'img-before-group'"
        ).fetchall()
        deleted_at = conn.execute(
            "SELECT deleted_at FROM images WHERE id = 'img-before-group'"
        ).fetchone()[0]

    assert {
        "idx_feed_publications_media_ready",
        "idx_feed_publications_category_ready_created",
        "idx_feed_publications_legacy_ready_created",
        "idx_images_user_deleted_created",
        "idx_images_user_favorite_deleted_created",
        "idx_images_active_user_created",
        "idx_images_job_id",
        "idx_image_sources_image",
        "idx_image_sources_user",
        "idx_image_sources_library_available",
        "idx_jobs_user_created",
        "idx_jobs_result_image",
    } <= indexes
    assert deleted_at is None
    assert len(search_rows) == 1
    assert search_rows[0]["user_id"] == "user-media"
    assert "синий город" in search_rows[0]["search_text"]
    assert "blue city" in search_rows[0]["search_text"]


def test_init_db_characterizes_core_defaults_and_is_idempotent(tmp_path, monkeypatch):
    path = tmp_path / "core-defaults.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", path)

    main.init_db()
    main.init_db()

    with open_sqlite(path) as conn:
        demo = conn.execute(
            "SELECT username, first_name, language, role FROM users WHERE id = 'demo_user'"
        ).fetchone()
        profiles = {
            row["id"]: row
            for row in conn.execute(
                "SELECT id, provider, model_name, supports_pose, settings_json "
                "FROM model_profiles WHERE id IN "
                "('local_flux_klein', 'flux_klein_4b', 'flux_klein_9b')"
            ).fetchall()
        }
        presets = {
            row["id"]: (row["name_ru"], row["name_en"], row["mode"])
            for row in conn.execute(
                "SELECT id, name_ru, name_en, mode FROM presets "
                "WHERE id IN ('portrait', 'enhance', 'collage')"
            ).fetchall()
        }
        challenge = conn.execute(
            "SELECT title, category, status, reward_pool, starts_at, ends_at "
            "FROM challenges WHERE id = 'moscow_2120_week'"
        ).fetchone()
        challenge_count = conn.execute(
            "SELECT COUNT(*) FROM challenges WHERE id = 'moscow_2120_week'"
        ).fetchone()[0]

    assert tuple(demo) == ("demo", "Demo", "ru", "admin")
    assert set(profiles) == {"local_flux_klein", "flux_klein_4b", "flux_klein_9b"}
    assert profiles["local_flux_klein"]["model_name"] == "flux-2-klein-9b-fp8.safetensors"
    settings_4b = json.loads(profiles["flux_klein_4b"]["settings_json"])
    settings_9b = json.loads(profiles["flux_klein_9b"]["settings_json"])
    assert profiles["flux_klein_4b"]["supports_pose"] == 0
    assert settings_4b["variant"] == "4b"
    assert settings_4b["pose"]["supported"] is False
    assert profiles["flux_klein_9b"]["supports_pose"] == 1
    assert settings_9b["variant"] == "9b"
    assert settings_9b["pose"]["lora"] == "refcontrol_v2_poses.safetensors"
    assert presets == {
        "portrait": ("Кинематографичный портрет", "Cinematic portrait", "text_to_image"),
        "enhance": ("Улучшить качество", "Enhance quality", "edit"),
        "collage": ("Коллаж в сцену", "Collage to scene", "paint"),
    }
    assert tuple(challenge) == (
        "Москва 2120",
        "challenge_moscow_2120",
        "active",
        10000,
        "2026-07-01T00:00:00+00:00",
        "2026-07-14T23:59:59+00:00",
    )
    assert challenge_count == 1


def test_media_schema_group_is_import_safe_and_idempotent(tmp_path):
    path = tmp_path / "media-schema-unit.sqlite3"
    with open_sqlite(path) as conn:
        conn.executescript(BASE_SCHEMA_SQL)
        add_missing_columns(conn, "users", {"internal_user_id": "TEXT"})
        add_missing_columns(conn, "images", IMAGE_ADDITIVE_COLUMNS)
        conn.executescript(IDENTITY_SCHEMA_SQL)
        conn.execute(
            """
            INSERT INTO images (
                id, user_id, job_id, url, thumbnail_url, prompt_original,
                prompt_translated, width, height, mode, provider, created_at
            ) VALUES (
                'img-unit-group', 'user-unit', 'job-unit', '/api/media/unit.png',
                '/api/media/unit.webp', 'белая башня', 'white tower',
                704, 704, 'text_to_image', 'comfyui', '2026-01-01'
            )
            """
        )

        initialize_media_schema_group(conn)
        initialize_media_schema_group(conn)

        assert {
            "media_ready_at",
            "category",
            "generation_snapshot_json",
        } <= table_columns(conn, "feed_publications")
        assert {
            "children_json",
            "library_deleted_at",
            "availability_status",
        } <= table_columns(conn, "image_sources")
        assert "deleted_at" in table_columns(conn, "images")
        rows = conn.execute(
            "SELECT image_id, search_text FROM images_search WHERE image_id = 'img-unit-group'"
        ).fetchall()

    assert len(rows) == 1
    assert "белая башня" in rows[0]["search_text"]
    assert "white tower" in rows[0]["search_text"]


def test_identity_schema_group_is_import_safe_and_idempotent(tmp_path):
    path = tmp_path / "identity-schema-unit.sqlite3"
    now = "2026-07-13T00:00:00+00:00"
    with open_sqlite(path) as conn:
        conn.executescript(BASE_SCHEMA_SQL)
        add_missing_columns(conn, "users", USER_EARLY_ADDITIVE_COLUMNS)

        prepare_identity_schema_group(conn, now=now)
        prepare_identity_schema_group(conn, now="later-value")
        conn.execute(
            """
            INSERT INTO users (
                id, telegram_id, username, first_name, language, role,
                created_at, last_login_at, internal_user_id
            ) VALUES (
                'telegram_unit', '4242', 'unit', 'Unit', 'ru', 'user', ?, ?, NULL
            )
            """,
            (now, now),
        )

        assigned_codes: dict[str, str] = {}

        def assign_public_code(db_conn: sqlite3.Connection, internal_user_id: str) -> str:
            code = assigned_codes.setdefault(internal_user_id, f"TEST-{len(assigned_codes) + 1:06d}")
            db_conn.execute(
                "UPDATE users SET public_user_code = ? "
                "WHERE internal_user_id = ? AND public_user_code IS NULL",
                (code, internal_user_id),
            )
            return code

        finalize_identity_schema_group(
            conn,
            now=now,
            ensure_public_user_code=assign_public_code,
        )
        finalize_identity_schema_group(
            conn,
            now="later-value",
            ensure_public_user_code=assign_public_code,
        )

        user = conn.execute(
            "SELECT internal_user_id, public_user_code FROM users WHERE id = 'telegram_unit'"
        ).fetchone()
        identity_count = conn.execute(
            "SELECT COUNT(*) FROM auth_identities "
            "WHERE provider = 'telegram' AND provider_user_id = '4242'"
        ).fetchone()[0]
        refresh_column = "refresh_expires_at" in table_columns(conn, "auth_sessions")
        indexes = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        editorial_count = conn.execute(
            "SELECT COUNT(*) FROM users WHERE id = 'seed_editorial'"
        ).fetchone()[0]

    assert user["internal_user_id"]
    assert user["public_user_code"].startswith("TEST-")
    assert identity_count == 1
    assert refresh_column is True
    assert editorial_count == 1
    assert {"ux_users_internal_user_id", "ux_users_public_user_code"} <= indexes


def test_core_schema_and_default_seeds_are_import_safe_and_idempotent(tmp_path):
    path = tmp_path / "core-schema-unit.sqlite3"
    now = "2026-07-13T00:00:00+00:00"
    with open_sqlite(path) as conn:
        prepare_core_schema_group(conn)
        prepare_core_schema_group(conn)
        seed_core_defaults(conn, now=now)
        seed_core_defaults(conn, now="later-value")
        prepare_identity_schema_group(conn, now=now)
        seed_default_challenge(conn, now=now)
        seed_default_challenge(conn, now="later-value")

        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        seed_counts = {
            "demo": conn.execute("SELECT COUNT(*) FROM users WHERE id = 'demo_user'").fetchone()[0],
            "profiles": conn.execute(
                "SELECT COUNT(*) FROM model_profiles WHERE id IN "
                "('local_flux_klein', 'flux_klein_4b', 'flux_klein_9b')"
            ).fetchone()[0],
            "presets": conn.execute(
                "SELECT COUNT(*) FROM presets WHERE id IN ('portrait', 'enhance', 'collage')"
            ).fetchone()[0],
            "challenge": conn.execute(
                "SELECT COUNT(*) FROM challenges WHERE id = 'moscow_2120_week'"
            ).fetchone()[0],
        }
        challenge_created_at = conn.execute(
            "SELECT created_at FROM challenges WHERE id = 'moscow_2120_week'"
        ).fetchone()[0]
        image_columns = table_columns(conn, "images")
        user_columns = table_columns(conn, "users")

    assert {
        "token_ledger",
        "billing_packages",
        "invoices",
        "invoice_items",
        "payments",
        "refunds",
        "referral_rewards",
    } <= tables
    assert {"deleted_at", "storage_tier"} <= image_columns
    assert {"public_user_code", "display_name"} <= user_columns
    assert seed_counts == {"demo": 1, "profiles": 3, "presets": 3, "challenge": 1}
    assert challenge_created_at == now


def test_migration_ledger_creation_is_empty_and_does_not_advance_version(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    with open_sqlite(path) as conn:
        ensure_migration_ledger(conn, supported_version=LEGACY_BASELINE_MIGRATION.version)
        assert sqlite_user_version(conn) == 0
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 0


def test_legacy_baseline_finalize_is_idempotent_and_advances_version(tmp_path):
    path = tmp_path / "baseline.sqlite3"
    with open_sqlite(path) as conn:
        assert finalize_legacy_schema_baseline(conn, applied_at="2026-07-13T00:00:00Z") is True
        assert finalize_legacy_schema_baseline(conn, applied_at="later-value") is False
        row = conn.execute(
            "SELECT version, name, checksum, applied_at FROM schema_migrations"
        ).fetchone()
        assert dict(row) == {
            "version": LEGACY_BASELINE_MIGRATION.version,
            "name": LEGACY_BASELINE_MIGRATION.name,
            "checksum": LEGACY_BASELINE_MIGRATION.checksum,
            "applied_at": "2026-07-13T00:00:00Z",
        }
        assert sqlite_user_version(conn) == 1


def test_migration_ledger_rejects_changed_applied_definition(tmp_path):
    path = tmp_path / "changed.sqlite3"
    with open_sqlite(path) as conn:
        finalize_legacy_schema_baseline(conn, applied_at="2026-07-13T00:00:00Z")
        changed = MigrationDefinition(
            version=1,
            name=LEGACY_BASELINE_MIGRATION.name,
            checksum="sha256:" + "0" * 64,
        )
        with pytest.raises(RuntimeError, match="MIGRATION_DEFINITION_MISMATCH"):
            record_applied_migration(conn, changed, applied_at="later-value")
        assert sqlite_user_version(conn) == 1


def test_migration_ledger_rejects_database_newer_than_code(tmp_path):
    path = tmp_path / "newer.sqlite3"
    with open_sqlite(path) as conn:
        conn.execute("PRAGMA user_version = 2")
        with pytest.raises(RuntimeError, match="DATABASE_SCHEMA_VERSION_UNSUPPORTED"):
            ensure_migration_ledger(conn, supported_version=1)
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        assert table is None


def test_migration_ledger_rejects_name_reuse_at_another_version(tmp_path):
    path = tmp_path / "name-reuse.sqlite3"
    with open_sqlite(path) as conn:
        finalize_legacy_schema_baseline(conn, applied_at="2026-07-13T00:00:00Z")
        reused = MigrationDefinition(
            version=2,
            name=LEGACY_BASELINE_MIGRATION.name,
            checksum="sha256:" + "1" * 64,
        )
        with pytest.raises(RuntimeError, match="MIGRATION_NAME_REUSED"):
            record_applied_migration(conn, reused, applied_at="later-value")
        assert sqlite_user_version(conn) == 1


def test_init_db_records_legacy_baseline_once(tmp_path, monkeypatch):
    path = tmp_path / "init-ledger.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", path)

    main.init_db()
    main.init_db()

    with open_sqlite(path) as conn:
        rows = conn.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert [dict(row) for row in rows] == [
            {
                "version": LEGACY_BASELINE_MIGRATION.version,
                "name": LEGACY_BASELINE_MIGRATION.name,
                "checksum": LEGACY_BASELINE_MIGRATION.checksum,
            }
        ]
        assert sqlite_user_version(conn) == 1


def test_init_db_rejects_newer_database_before_schema_mutation(tmp_path, monkeypatch):
    path = tmp_path / "newer-init.sqlite3"
    with open_sqlite(path) as conn:
        conn.execute("PRAGMA user_version = 2")
    monkeypatch.setattr(main, "DB_PATH", path)

    with pytest.raises(RuntimeError, match="DATABASE_SCHEMA_VERSION_UNSUPPORTED"):
        main.init_db()

    with open_sqlite(path) as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "schema_migrations" not in tables
        assert "users" not in tables
        assert sqlite_user_version(conn) == 2
