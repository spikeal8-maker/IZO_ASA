"""Unit contracts for import-safe SQLite connection and DB Guard modules."""

from __future__ import annotations

import sqlite3

import pytest

import main

from app.database import (
    BASE_SCHEMA_SQL,
    IDENTITY_SCHEMA_SQL,
    IMAGE_SEARCH_SCHEMA_SQL,
    LEGACY_BASELINE_MIGRATION,
    MigrationDefinition,
    DbGuardError,
    add_missing_columns,
    collect_sqlite_guard_status,
    open_sqlite,
    parse_allowed_database_paths,
    preflight_sqlite_database,
    ensure_migration_ledger,
    finalize_legacy_schema_baseline,
    record_applied_migration,
    safe_guard_payload,
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
