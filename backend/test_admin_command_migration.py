"""Disposable schema upgrade, atomic failure and restored-snapshot compatibility."""
from __future__ import annotations

from contextlib import closing
import hashlib
import sqlite3

import pytest

from app.database import migrations
from app.database.admin_command_schema import ADMIN_COMMAND_SCHEMA_SQL


PREVIOUS = migrations.PHONE_CHAT_REQUEST_LIFECYCLE_MIGRATION.version
NOW = "2026-10-19T00:00:00+00:00"


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def old_database(path):
    with closing(connect(path)) as conn, conn:
        for definition in (
            migrations.LEGACY_BASELINE_MIGRATION, migrations.ADMIN_NOTIFICATIONS_MIGRATION,
            migrations.ADMIN_NOTIFICATION_DELIVERY_MIGRATION, migrations.ACCOUNT_VERIFICATION_MIGRATION,
            migrations.PHONE_CHAT_HISTORY_MIGRATION, migrations.GENERATION_TRIAL_MIGRATION,
            migrations.PHONE_CHAT_REQUEST_LIFECYCLE_MIGRATION,
        ):
            migrations.record_applied_migration(conn, definition, applied_at=NOW)
        conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, token_balance INTEGER, plan TEXT, plan_expires_at TEXT)")
        conn.execute("CREATE TABLE token_ledger (id TEXT PRIMARY KEY, user_id TEXT, delta INTEGER)")
        conn.execute("CREATE TABLE tariff_token_grants (id TEXT PRIMARY KEY, user_id TEXT, grant_key TEXT UNIQUE)")
        conn.execute("INSERT INTO users VALUES ('existing', 75, 'pro', '2026-11-01')")
        conn.execute("INSERT INTO token_ledger VALUES ('ledger-before', 'existing', 25)")
        conn.execute("INSERT INTO tariff_token_grants VALUES ('grant-before', 'existing', 'before-upgrade-key')")


def data(conn):
    return {table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1")]
            for table in ("users", "token_ledger", "tariff_token_grants")}


def dump(conn):
    return "\n".join(conn.iterdump())


def test_new_migration_identity_matches_the_frozen_additive_schema():
    definition = migrations.ADMIN_COMMANDS_MIGRATION
    assert definition.version == PREVIOUS + 1
    assert definition.name == "admin_entitlement_commands"
    assert definition.checksum == "sha256:" + hashlib.sha256(ADMIN_COMMAND_SCHEMA_SQL.encode()).hexdigest()


def test_upgrade_preserves_existing_financial_rows_and_repeats_without_rewrite(tmp_path):
    path = tmp_path / "previous.sqlite3"
    old_database(path)
    with closing(connect(path)) as conn, conn:
        before = data(conn)
        existing_ledger = [tuple(row) for row in conn.execute("SELECT * FROM schema_migrations ORDER BY version")]
        assert migrations.apply_admin_commands_migration(conn, applied_at=NOW) is True
        assert data(conn) == before
        assert migrations.sqlite_user_version(conn) == migrations.ADMIN_COMMANDS_MIGRATION.version
        assert [tuple(row) for row in conn.execute("SELECT * FROM schema_migrations WHERE version <= ? ORDER BY version", (PREVIOUS,))] == existing_ledger
        conn.execute("INSERT INTO admin_commands VALUES ('receipt', 'existing-admin-command', 'actor', 'target', 'operation', ?, '{}', ?)", ("f" * 64, NOW))
        after = dump(conn)
        assert migrations.apply_admin_commands_migration(conn, applied_at="2099-01-01") is False
        assert dump(conn) == after
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_ledger_write_failure_rolls_back_new_table_version_and_business_rows(tmp_path, monkeypatch):
    path = tmp_path / "previous.sqlite3"
    old_database(path)
    with closing(connect(path)) as conn, conn:
        before = dump(conn)

        def unavailable(*args, **kwargs):
            raise RuntimeError("controlled migration ledger failure")

        monkeypatch.setattr(migrations, "record_applied_migration", unavailable)
        with pytest.raises(RuntimeError, match="controlled migration ledger failure"):
            migrations.apply_admin_commands_migration(conn, applied_at=NOW)
        assert dump(conn) == before
        assert migrations.sqlite_user_version(conn) == PREVIOUS
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='admin_commands'").fetchone() is None


def test_failure_after_ledger_and_user_version_write_rolls_back_every_change(tmp_path, monkeypatch):
    path = tmp_path / "previous.sqlite3"
    old_database(path)
    original = migrations.record_applied_migration
    with closing(connect(path)) as conn, conn:
        before = dump(conn)

        def fail_after_record(*args, **kwargs):
            assert original(*args, **kwargs) is True
            assert migrations.sqlite_user_version(args[0]) == migrations.ADMIN_COMMANDS_MIGRATION.version
            raise RuntimeError("controlled failure after ledger and user_version")

        monkeypatch.setattr(migrations, "record_applied_migration", fail_after_record)
        with pytest.raises(RuntimeError, match="controlled failure after ledger and user_version"):
            migrations.apply_admin_commands_migration(conn, applied_at=NOW)
        assert dump(conn) == before
        assert migrations.sqlite_user_version(conn) == PREVIOUS


@pytest.mark.parametrize("future_location", ["user_version", "ledger"])
def test_future_schema_is_rejected_before_a_new_command_migration(tmp_path, future_location):
    path = tmp_path / "future.sqlite3"
    old_database(path)
    with closing(connect(path)) as conn, conn:
        if future_location == "user_version":
            conn.execute("PRAGMA user_version = 9")
        else:
            conn.execute("INSERT INTO schema_migrations VALUES (9, 'future_schema', ?, ?)", ("sha256:" + "9" * 64, NOW))
        before = dump(conn)
        with pytest.raises(RuntimeError, match="VERSION_UNSUPPORTED"):
            migrations.apply_admin_commands_migration(conn, applied_at=NOW)
        assert dump(conn) == before
        with pytest.raises(RuntimeError, match="VERSION_UNSUPPORTED"):
            migrations.ensure_migration_ledger(conn, supported_version=migrations.ADMIN_COMMANDS_MIGRATION.version)


@pytest.mark.parametrize("column, value", [("checksum", "sha256:" + "0" * 64), ("name", "changed_admin_definition")])
def test_mismatched_applied_metadata_fails_without_schema_or_data_rewrite(tmp_path, column, value):
    path = tmp_path / "previous.sqlite3"
    old_database(path)
    with closing(connect(path)) as conn, conn:
        migrations.apply_admin_commands_migration(conn, applied_at=NOW)
        conn.execute(f"UPDATE schema_migrations SET {column}=? WHERE version=?", (value, migrations.ADMIN_COMMANDS_MIGRATION.version))
        before = dump(conn)
        with pytest.raises(RuntimeError, match="MIGRATION_DEFINITION_MISMATCH"):
            migrations.apply_admin_commands_migration(conn, applied_at=NOW)
        assert dump(conn) == before


@pytest.mark.parametrize("future_location", ["user_version", "ledger"])
def test_caller_guards_future_state_and_supported_future_caller_can_repeat_applied_v8(tmp_path, future_location):
    path = tmp_path / "upgraded.sqlite3"
    old_database(path)
    with closing(connect(path)) as conn, conn:
        migrations.apply_admin_commands_migration(conn, applied_at=NOW)
        if future_location == "user_version":
            conn.execute("PRAGMA user_version = 9")
        else:
            conn.execute("INSERT INTO schema_migrations VALUES (9, 'future_schema', ?, ?)", ("sha256:" + "9" * 64, NOW))
        before = dump(conn)
        # This is the upfront init_db admission boundary, before all helpers.
        with pytest.raises(RuntimeError, match="VERSION_UNSUPPORTED"):
            migrations.ensure_migration_ledger(conn, supported_version=migrations.ADMIN_COMMANDS_MIGRATION.version)
        assert dump(conn) == before
        # A future binary can still repeat its older, already-applied migrations.
        migrations.ensure_migration_ledger(conn, supported_version=9)
        assert migrations.apply_admin_commands_migration(conn, applied_at="2099-01-01") is False
        assert dump(conn) == before


def test_old_binary_refuses_upgraded_state_and_accepts_restored_preupgrade_snapshot(tmp_path):
    active, backup, restored = (tmp_path / name for name in ("active.sqlite3", "backup.sqlite3", "restored.sqlite3"))
    old_database(active)
    with closing(connect(active)) as conn, closing(connect(backup)) as snapshot:
        before = data(conn)
        conn.backup(snapshot)
        with conn:
            migrations.apply_admin_commands_migration(conn, applied_at=NOW)
        with pytest.raises(RuntimeError, match="DATABASE_SCHEMA_VERSION_UNSUPPORTED"):
            migrations.ensure_migration_ledger(conn, supported_version=PREVIOUS)
    with closing(connect(backup)) as snapshot, closing(connect(restored)) as recovered:
        snapshot.backup(recovered)
        migrations.ensure_migration_ledger(recovered, supported_version=PREVIOUS)
        assert migrations.sqlite_user_version(recovered) == PREVIOUS
        assert data(recovered) == before
        assert recovered.execute("SELECT 1 FROM sqlite_master WHERE name='admin_commands'").fetchone() is None


def test_applied_migration_with_missing_receipts_table_fails_without_silent_recreation(tmp_path):
    path = tmp_path / "previous.sqlite3"
    old_database(path)
    with closing(connect(path)) as conn, conn:
        migrations.apply_admin_commands_migration(conn, applied_at=NOW)
        conn.execute("DROP TABLE admin_commands")
        before = dump(conn)
        with pytest.raises(RuntimeError, match="ADMIN_COMMAND_SCHEMA_INVALID"):
            migrations.apply_admin_commands_migration(conn, applied_at=NOW)
        assert dump(conn) == before


def test_unregistered_table_is_not_adopted_as_empty_history(tmp_path):
    path = tmp_path / "previous.sqlite3"
    old_database(path)
    with closing(connect(path)) as conn, conn:
        conn.execute(ADMIN_COMMAND_SCHEMA_SQL)
        before = dump(conn)
        with pytest.raises(RuntimeError, match="ADMIN_COMMAND_SCHEMA_UNREGISTERED"):
            migrations.apply_admin_commands_migration(conn, applied_at=NOW)
        assert dump(conn) == before
        assert migrations.sqlite_user_version(conn) == PREVIOUS
