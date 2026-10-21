"""Disposable SQLite/media checks; never Docker, production or live providers."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from tools import docker_shadow_storage as storage


@pytest.fixture
def fixture(tmp_path):
    source = tmp_path / "fixture"
    media = source / "media"
    media.mkdir(parents=True)
    (media / "image.png").write_bytes(b"fixture-image")
    (media / "thumb.webp").write_bytes(b"fixture-thumbnail")
    database = source / "app.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.executescript("""
            CREATE TABLE users(id TEXT PRIMARY KEY, private_value TEXT);
            CREATE TABLE jobs(id TEXT PRIMARY KEY, status TEXT, user_id TEXT REFERENCES users(id));
            CREATE TABLE images(id TEXT PRIMARY KEY, url TEXT, thumbnail_url TEXT);
            CREATE TABLE image_sources(id TEXT PRIMARY KEY, thumb_url TEXT);
            CREATE TABLE schema_migrations(version INTEGER, name TEXT, checksum TEXT);
            INSERT INTO users VALUES('fixture-user','PRIVATE-FIXTURE-SENTINEL');
            INSERT INTO jobs VALUES('fixture-job','completed','fixture-user');
            INSERT INTO images VALUES('fixture-image','/api/media/image.png?userId=fixture-user','/media/thumb.webp');
            INSERT INTO image_sources VALUES('fixture-source','/api/media/thumb.webp');
            INSERT INTO schema_migrations VALUES(1,'fixture-schema','fixture-checksum');
        """)
        connection.commit()
    scope = {"project": "izo-asa-shadow-storage-fixture", "sourceSha": "a" * 40,
             "isolatedData": True, "fakeProviderOnly": True, "externalEffectsDisabled": True,
             "networkEgressDenied": True, "database": "app.sqlite3", "media": "media"}
    scope_file = source / "scope.json"
    scope_file.write_text(json.dumps(scope), encoding="utf-8")
    work = tmp_path / "owned-work"
    work.mkdir()
    return scope_file, database, media, work, scope


def test_backup_restore_logical_rows_migration_ledger_media_and_negative_cases(fixture):
    scope, database, media, work, _ = fixture
    before = {p.relative_to(scope.parent).as_posix(): p.read_bytes()
              for p in scope.parent.rglob("*") if p.is_file()}
    result = storage.rehearse(scope, work)
    assert result["status"] == "STORAGE_REHEARSAL_PASS"
    assert result["restore"] == result["cleanup"] == result["sourceUnchanged"] == "PASS"
    assert set(result["negativeCases"]) == {"database", "media", "incomplete"}
    assert result["sourceState"]["database"]["imageReferences"] == 3
    assert result["sourceState"]["database"]["migrationLedger"]["rows"] == 1
    assert result["freshDockerVolumes"] == result["restoredApplication"] == "NOT_VERIFIED"
    assert "PRIVATE-FIXTURE-SENTINEL" not in json.dumps(result)
    assert str(database) not in json.dumps(result)
    assert not list(work.iterdir())
    assert before == {p.relative_to(scope.parent).as_posix(): p.read_bytes()
                      for p in scope.parent.rglob("*") if p.is_file()}


def test_committed_wal_rows_included_with_caller_writer_open(fixture):
    scope, database, _, work, _ = fixture
    with closing(sqlite3.connect(database)) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("INSERT INTO users VALUES('wal-user','PRIVATE-WAL-VALUE')")
        writer.commit()
        assert Path(str(database) + "-wal").stat().st_size > 0
        result = storage.rehearse(scope, work)
        assert result["sourceState"]["database"]["tables"]["users"]["rows"] == 2
        assert not list(work.iterdir())


def test_all_test_owned_sqlite_connections_closed_on_success(fixture, monkeypatch):
    scope, _, _, work, _ = fixture
    original = sqlite3.connect
    opened = []
    def tracked(*args, **kwargs):
        connection = original(*args, **kwargs)
        opened.append(connection)
        return connection
    monkeypatch.setattr(sqlite3, "connect", tracked)
    storage.rehearse(scope, work)
    assert opened
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")
    assert not list(work.iterdir())


@pytest.mark.parametrize("key,value", [
    ("isolatedData", False), ("fakeProviderOnly", "true"), ("networkEgressDenied", 1),
    ("externalEffectsDisabled", None), ("project", "foreign-project"), ("sourceSha", "dirty"),
    ("database", "../outside.sqlite3"), ("media", "../outside-media"),
], ids=["not-isolated", "fake-string", "egress-integer", "effects-null", "foreign", "sha",
        "database-escape", "media-escape"])
def test_invalid_scope_fails_before_copy_or_write(fixture, key, value):
    scope, _, _, work, values = fixture
    values[key] = value
    scope.write_text(json.dumps(values), encoding="utf-8")
    with pytest.raises(storage.RehearsalError):
        storage.rehearse(scope, work)
    assert not list(work.iterdir())


@pytest.mark.parametrize("case", ["missing-media", "bad-url", "foreign-key", "empty-ledger"])
def test_invalid_fixture_detected_before_backup(fixture, case):
    scope, database, media, work, _ = fixture
    if case == "missing-media":
        (media / "image.png").unlink()
    else:
        with closing(sqlite3.connect(database)) as connection:
            if case == "bad-url":
                connection.execute("UPDATE images SET url='/api/media/../../private'")
            elif case == "foreign-key":
                connection.execute("UPDATE jobs SET user_id='nonexistent'")
            else:
                connection.execute("DELETE FROM schema_migrations")
            connection.commit()
    with pytest.raises((storage.RehearsalError, ValueError)):
        storage.rehearse(scope, work)
    assert not list(work.iterdir())


def test_cleanup_on_restore_exception_preserves_source_and_foreign_file(fixture, monkeypatch):
    scope, database, _, work, _ = fixture
    foreign = work / "foreign-evidence.txt"
    foreign.write_text("must remain")
    before = database.read_bytes()
    def failed(*_):
        raise RuntimeError("PRIVATE-RESTORE-DETAIL")
    monkeypatch.setattr(storage, "restore_snapshot", failed)
    with pytest.raises(RuntimeError, match="PRIVATE-RESTORE-DETAIL"):
        storage.rehearse(scope, work)
    assert list(work.iterdir()) == [foreign]
    assert foreign.read_text() == "must remain" and database.read_bytes() == before


def test_cli_emits_only_safe_receipt_and_never_overwrites_existing_file(fixture):
    scope, _, _, work, values = fixture
    values["isolatedData"] = False
    scope.write_text(json.dumps(values), encoding="utf-8")
    receipt = work / "receipt.json"
    args = [sys.executable, "-B", "tools/docker_shadow_storage.py", "--fixture-scope", str(scope),
            "--work-parent", str(work), "--receipt", str(receipt)]
    result = subprocess.run(args, capture_output=True, text=True, timeout=10)
    assert result.returncode == 1 and result.stdout.strip() == "FAIL" and not result.stderr
    observed = json.loads(receipt.read_text())
    assert observed == {"status": "FAIL", "exceptionType": "RehearsalError",
                        "code": "FIXTURE_ISOLATION_NOT_ATTESTED"}
    before = receipt.read_bytes()
    second = subprocess.run(args, capture_output=True, text=True, timeout=10)
    assert second.returncode == 1 and second.stdout.strip() == "RECEIPT_WRITE_FAILED"
    assert receipt.read_bytes() == before


def test_work_directory_inside_fixture_is_rejected(fixture):
    scope, _, media, _, _ = fixture
    with pytest.raises(storage.RehearsalError, match="REHEARSAL_WORKSPACE_INVALID"):
        storage.rehearse(scope, media)


def test_cli_cannot_write_receipt_inside_source_even_with_ancestor_work_parent(fixture):
    scope, _, _, _, _ = fixture
    receipt = scope.parent / "unowned-receipt.json"
    result = subprocess.run([sys.executable, "-B", "tools/docker_shadow_storage.py",
        "--fixture-scope", str(scope), "--work-parent", str(scope.parent.parent),
        "--receipt", str(receipt)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 1 and result.stdout.strip() == "RECEIPT_WRITE_FAILED"
    assert not result.stderr and not receipt.exists()
