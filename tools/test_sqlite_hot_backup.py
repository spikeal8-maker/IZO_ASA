from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from sqlite_hot_backup import HotBackupError, backup_database  # noqa: E402


def test_hot_backup_includes_committed_wal_rows_while_source_is_open(tmp_path: Path) -> None:
    source = tmp_path / "live.sqlite3"
    destination = tmp_path / "rollback" / "database.sqlite3"
    with sqlite3.connect(source) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        writer.execute("INSERT INTO records(value) VALUES ('before')")
        writer.commit()
        writer.execute("INSERT INTO records(value) VALUES ('committed-in-wal')")
        writer.commit()

        size = backup_database(source, destination)

        assert writer.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 2

    assert size == destination.stat().st_size
    with sqlite3.connect(destination) as restored:
        assert restored.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert restored.execute("SELECT value FROM records ORDER BY id").fetchall() == [
            ("before",),
            ("committed-in-wal",),
        ]


def test_hot_backup_never_overwrites_an_existing_rollback(tmp_path: Path) -> None:
    source = tmp_path / "live.sqlite3"
    destination = tmp_path / "database.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
    destination.write_bytes(b"preserve")

    try:
        backup_database(source, destination)
    except HotBackupError as exc:
        assert str(exc) == "destination_already_exists"
    else:
        raise AssertionError("existing rollback database was overwritten")

    assert destination.read_bytes() == b"preserve"
