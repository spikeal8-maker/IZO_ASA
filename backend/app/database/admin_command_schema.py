"""Additive storage for completed local administrative commands.

Migration registration and its allocated version belong to migrations.py. This
module contains no import-time connection or schema mutation.
"""
import sqlite3

ADMIN_COMMAND_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS admin_commands (
    id TEXT PRIMARY KEY,
    command_key TEXT NOT NULL UNIQUE CHECK (length(command_key) BETWEEN 12 AND 120),
    actor_internal_user_id TEXT NOT NULL,
    target_internal_user_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    request_sha256 TEXT NOT NULL CHECK (length(request_sha256) = 64),
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""


def validate_admin_command_schema(conn: sqlite3.Connection) -> None:
    """An applied migration must not silently replace lost replay history."""
    columns = {row["name"]: row for row in conn.execute("PRAGMA table_info(admin_commands)")}
    required = {"id", "command_key", "actor_internal_user_id", "target_internal_user_id",
                "operation", "request_sha256", "response_json", "created_at"}
    if (not required <= columns.keys() or columns["id"]["pk"] != 1
            or any(columns[name]["type"].upper() != "TEXT" for name in required)
            or any(not columns[name]["notnull"] for name in required - {"id"})):
        raise RuntimeError("ADMIN_COMMAND_SCHEMA_INVALID")
    unique_key = any(
        row["unique"] and not row["partial"]
        and [item["name"] for item in conn.execute("SELECT name FROM pragma_index_info(?) ORDER BY seqno", (row["name"],))] == ["command_key"]
        for row in conn.execute("PRAGMA index_list(admin_commands)")
    )
    if not unique_key:
        raise RuntimeError("ADMIN_COMMAND_SCHEMA_KEY_NOT_UNIQUE")
