"""Create an atomic, consistent SQLite backup while the application stays online."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import uuid
from contextlib import closing
from pathlib import Path


class HotBackupError(RuntimeError):
    """A hot-backup safety invariant was not satisfied."""


def backup_database(source: Path, destination: Path) -> int:
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if not source.is_file():
        raise HotBackupError("source_database_not_found")
    if source == destination:
        raise HotBackupError("source_and_destination_must_differ")
    if destination.exists():
        raise HotBackupError("destination_already_exists")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.partial")
    source_uri = source.as_uri() + "?mode=ro"
    try:
        with closing(sqlite3.connect(source_uri, uri=True, timeout=30)) as source_connection:
            source_connection.execute("PRAGMA query_only = ON")
            with closing(sqlite3.connect(temporary)) as destination_connection:
                source_connection.backup(destination_connection, pages=2048, sleep=0.05)
                destination_connection.commit()
                result = destination_connection.execute("PRAGMA quick_check").fetchone()
                if result is None or result[0] != "ok":
                    raise HotBackupError("destination_quick_check_failed")
        os.replace(temporary, destination)
        return destination.stat().st_size
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    try:
        size = backup_database(args.source, args.destination)
        print(f"SQLITE_HOT_BACKUP_OK bytes={size}")
        return 0
    except (HotBackupError, OSError, sqlite3.Error) as exc:
        print(f"SQLITE_HOT_BACKUP_ERROR reason={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
