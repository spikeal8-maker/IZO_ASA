"""Real SQLite races and failure boundaries for local admin command storage."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from threading import Barrier

import pytest

from app.database.admin_command_schema import ADMIN_COMMAND_SCHEMA_SQL
from app.services.admin_commands import (
    AdminCommandError, execute_local_command, normalize_reason,
)


def connect(path: Path):
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


@pytest.fixture
def state(tmp_path):
    path = tmp_path / "commands.sqlite3"
    with closing(connect(path)) as conn, conn:
        conn.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE users (
                internal_user_id TEXT PRIMARY KEY, role TEXT NOT NULL,
                banned INTEGER NOT NULL DEFAULT 0, balance INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE ledger (id TEXT PRIMARY KEY, target TEXT, delta INTEGER);
            CREATE TABLE audit (id TEXT PRIMARY KEY, reason TEXT);
            INSERT INTO users VALUES ('actor', 'admin', 0, 0);
            INSERT INTO users VALUES ('actor-two', 'admin', 0, 0);
            INSERT INTO users VALUES ('target', 'user', 0, 20);
        """)
        conn.execute(ADMIN_COMMAND_SCHEMA_SQL)
    return path


def apply(path, *, key="command-00000001", actor="actor", target="target", delta=5,
          operation="tokens", reason="correction", fail_audit=False):
    with closing(connect(path)) as conn, conn:
        def mutate(command):
            before = conn.execute(
                "SELECT balance FROM users WHERE internal_user_id=?", (target,),
            ).fetchone()["balance"]
            if before + delta < 0:
                raise AdminCommandError(400, "insufficient balance")
            conn.execute("UPDATE users SET balance=? WHERE internal_user_id=?", (before + delta, target))
            conn.execute("INSERT INTO ledger VALUES (?, ?, ?)", (command.id, target, delta))
            if fail_audit:
                raise RuntimeError("injected audit failure")
            conn.execute("INSERT INTO audit VALUES (?, ?)", (command.id, reason))
            return {"old_balance": before, "new_balance": before + delta,
                    "created_at": command.now.isoformat(), "command_id": command.id}

        return execute_local_command(
            conn, key=key, actor_internal_user_id=actor, target_internal_user_id=target,
            operation=operation, payload={"delta": delta, "reason": reason}, mutate=mutate,
        )


def snapshot(path):
    with closing(connect(path)) as conn:
        return {
            "balance": conn.execute("SELECT balance FROM users WHERE internal_user_id='target'").fetchone()[0],
            "ledger": conn.execute("SELECT COUNT(*) FROM ledger").fetchone()[0],
            "audit": conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0],
            "commands": conn.execute("SELECT COUNT(*) FROM admin_commands").fetchone()[0],
        }


@pytest.mark.parametrize("trial", range(5))
def test_concurrent_same_command_changes_balance_once(state, trial):
    barrier = Barrier(2)

    def run():
        barrier.wait(timeout=5)
        return apply(state, key=f"same-command-{trial:04d}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]
    assert results[0].response == results[1].response
    assert sorted(result.replayed for result in results) == [False, True]
    assert snapshot(state) == {"balance": 25, "ledger": 1, "audit": 1, "commands": 1}


@pytest.mark.parametrize("trial", range(5))
def test_distinct_concurrent_debits_cannot_overdraw_or_overwrite(state, trial):
    barrier = Barrier(2)

    def run(index):
        barrier.wait(timeout=5)
        try:
            return apply(state, key=f"debit-{trial:04d}-{index:04d}", delta=-15)
        except AdminCommandError as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, index) for index in range(2)]
        results = [future.result(timeout=15) for future in futures]
    assert len([result for result in results if result == 400]) == 1
    assert snapshot(state) == {"balance": 5, "ledger": 1, "audit": 1, "commands": 1}


@pytest.mark.parametrize("trial", range(5))
def test_concurrent_conflicting_payload_has_one_deterministic_conflict(state, trial):
    barrier = Barrier(2)

    def run(delta):
        barrier.wait(timeout=5)
        try:
            return apply(state, key=f"conflict-command-{trial:04d}", delta=delta)
        except AdminCommandError as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, delta) for delta in (5, 7)]
        results = [future.result(timeout=15) for future in futures]
    assert len([result for result in results if result == 409]) == 1
    observed = snapshot(state)
    assert observed["balance"] in {25, 27}
    assert [observed[name] for name in ("ledger", "audit", "commands")] == [1, 1, 1]


def test_committed_result_survives_lost_response_and_reopen(state):
    first = apply(state)
    second = apply(state)
    assert second.replayed is True
    assert first.response == second.response
    with closing(connect(state)) as conn:
        stored = conn.execute("SELECT response_json FROM admin_commands").fetchone()[0]
    assert json.loads(stored) == first.response
    assert snapshot(state) == {"balance": 25, "ledger": 1, "audit": 1, "commands": 1}


@pytest.mark.parametrize("change", [
    {"delta": 7}, {"actor": "actor-two"}, {"target": "actor-two"},
    {"operation": "plan"}, {"reason": "different intent"},
])
def test_global_key_is_bound_to_actor_target_operation_and_payload(state, change):
    apply(state)
    with pytest.raises(AdminCommandError) as error:
        apply(state, **change)
    assert error.value.status_code == 409
    assert snapshot(state) == {"balance": 25, "ledger": 1, "audit": 1, "commands": 1}


@pytest.mark.parametrize("key", [None, "", "short", " key-with-spaces ", "a" * 121, "key-00000001\n", 1])
def test_missing_or_invalid_key_has_no_side_effect(state, key):
    with pytest.raises(AdminCommandError) as error:
        apply(state, key=key)
    assert error.value.status_code == 400
    assert snapshot(state) == {"balance": 20, "ledger": 0, "audit": 0, "commands": 0}


@pytest.mark.parametrize("field, value", [("role", "user"), ("banned", 1)])
def test_current_actor_permission_is_rechecked_before_replay(state, field, value):
    apply(state)
    with closing(connect(state)) as conn, conn:
        if field == "role":
            conn.execute("UPDATE users SET role=? WHERE internal_user_id='actor'", (value,))
        else:
            conn.execute("UPDATE users SET banned=? WHERE internal_user_id='actor'", (value,))
    with pytest.raises(AdminCommandError) as error:
        apply(state)
    assert error.value.status_code == 403
    assert snapshot(state) == {"balance": 25, "ledger": 1, "audit": 1, "commands": 1}


def test_audit_failure_rolls_back_balance_ledger_and_command(state):
    with pytest.raises(RuntimeError, match="injected audit failure"):
        apply(state, fail_audit=True)
    assert snapshot(state) == {"balance": 20, "ledger": 0, "audit": 0, "commands": 0}
    assert apply(state).response["new_balance"] == 25


def test_receipt_failure_rolls_back_balance_ledger_and_audit(state):
    with closing(connect(state)) as conn, conn:
        conn.execute("""CREATE TRIGGER reject_receipt BEFORE INSERT ON admin_commands
                        BEGIN SELECT RAISE(ABORT, 'injected receipt failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="injected receipt failure"):
        apply(state)
    assert snapshot(state) == {"balance": 20, "ledger": 0, "audit": 0, "commands": 0}


def test_reason_is_normalized_and_bounded():
    assert normalize_reason("  correction \n") == "correction"
    for invalid in (None, "", " \n\t", "x" * 501):
        with pytest.raises(AdminCommandError):
            normalize_reason(invalid)
