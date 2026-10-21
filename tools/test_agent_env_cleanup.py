"""SQLite handle ownership must be released before deleting test environments."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tools.agent_system import env_lifecycle as lifecycle
from tools import test_agent_env_ready as ready_cases


@pytest.mark.parametrize("scenario", ("fixture", "tables", "idempotent", "query-error"))
def test_sqlite_connections_close_before_owned_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str,
) -> None:
    connect, down = sqlite3.connect, lifecycle.env_down
    connections: list[sqlite3.Connection] = []
    cleanup_calls: list[Path] = []

    class QueryFailureConnection(sqlite3.Connection):
        def execute(self, statement, *args, **kwargs):
            if statement == "SELECT 1":
                raise RuntimeError("synthetic query failure")
            return super().execute(statement, *args, **kwargs)

    def tracked_connect(*args, **kwargs):
        if scenario == "query-error":
            kwargs["factory"] = QueryFailureConnection
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    def checked_down(worktree, **kwargs):
        cleanup_calls.append(worktree)
        try:
            assert connections
            for connection in connections:
                with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
                    connection.cursor()
        finally:
            for connection in connections:
                connection.close()
            result = down(worktree, **kwargs)
        return result

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)
    monkeypatch.setattr(lifecycle, "env_down", checked_down)
    scenarios = {
        "fixture": ready_cases.test_prepare_creates_initialized_sqlite_fixture,
        "tables": ready_cases.test_database_integrity_and_required_tables,
        "idempotent": ready_cases.test_database_initialization_is_idempotent,
        "query-error": ready_cases.test_prepare_creates_initialized_sqlite_fixture,
    }
    if scenario == "query-error":
        with pytest.raises(RuntimeError, match="synthetic query failure"):
            scenarios[scenario](tmp_path)
    else:
        scenarios[scenario](tmp_path)
    assert len(cleanup_calls) == 1
    assert not list(tmp_path.rglob("*.sqlite3"))
    for receipt in tmp_path.rglob("environment-receipt.json"):
        assert json.loads(receipt.read_text(encoding="utf-8"))["state"] == "stopped"
