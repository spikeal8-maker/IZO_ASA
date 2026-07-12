"""Low-level SQLite connection policy.

Importing this module never opens a database. Callers must pass the database
path explicitly so tests and future application factories can select it safely.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def open_sqlite(
    path: str | Path,
    *,
    timeout_seconds: float = 10,
    busy_timeout_ms: int = 10_000,
) -> sqlite3.Connection:
    """Open SQLite with the concurrency and integrity policy used by the app."""
    conn = sqlite3.connect(path, timeout=timeout_seconds)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.DatabaseError:
        # Some temporary/read-only SQLite environments cannot switch journal
        # mode. busy_timeout and foreign key enforcement remain active.
        pass
    return conn
