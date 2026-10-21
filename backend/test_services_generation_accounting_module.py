from __future__ import annotations

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest

from app.services import generation_accounting as accounting


@pytest.fixture
def owned_databases(tmp_path):
    directory = tmp_path / "owned-accounting"
    directory.mkdir()
    yield directory
    # All test connections are explicitly closed, including exception paths.
    # On Windows unlink also checks that SQLite no longer holds these files.
    for path in directory.iterdir():
        assert path.is_file() and path.suffix in {".sqlite", ".sqlite-wal", ".sqlite-shm"}
        path.unlink()
    directory.rmdir()
    assert not directory.exists()


def seed(directory, kind="balance", *, charged_at=None):
    path = directory / f"{kind}.sqlite"
    now = datetime.now(timezone.utc)
    balance, daily, monthly = {"balance": (100, 0, 0), "daily": (0, 100, 0),
                               "mixed": (40, 60, 0), "monthly": (40, 0, 60)}[kind]
    reason = "openrouter_monthly_generation" if monthly else "daily_generation" if not balance else "generation"
    meta = {"jobId": "fixture-job", "token_cost": 100}
    if monthly:
        meta.update(openrouter_monthly_used_before=0, openrouter_monthly_used_after=monthly)
    else:
        meta.update(daily_part=daily, balance_part=balance)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE users (id TEXT PRIMARY KEY,token_balance INTEGER,
                daily_tokens_used INTEGER,last_daily_reset TEXT,
                openrouter_monthly_tokens_used INTEGER,last_openrouter_month_reset TEXT,
                tokens_used INTEGER,generation_count INTEGER);
            CREATE TABLE token_ledger (id TEXT PRIMARY KEY,user_id TEXT,delta INTEGER,
                reason TEXT,meta_json TEXT,created_at TEXT);
        """)
        conn.execute("INSERT INTO users VALUES (?,?,?,?,?,?,100,1)",
                     ("fixture-user", 500 - balance, daily, now.strftime("%Y-%m-%d"),
                      monthly, now.strftime("%Y-%m")))
        conn.execute("INSERT INTO token_ledger VALUES (?,?,?,?,?,?)",
                     ("fixture-charge", "fixture-user", -balance, reason,
                      json.dumps(meta), (charged_at or now).isoformat()))
    return path


def transition(path, action, *, barrier=None):
    with closing(sqlite3.connect(path, timeout=5)) as conn, conn:
        conn.row_factory = sqlite3.Row
        if barrier is not None:
            barrier.wait(timeout=5)
        if action == "cancel":
            return accounting.refund_generation_tokens(conn, "fixture-job", reason="fixture-cancel")
        return accounting.reconcile_openrouter_token_charge(conn, "fixture-job", 40)


def observe(path):
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        user = dict(conn.execute("SELECT * FROM users").fetchone())
        ledger = [dict(row) for row in conn.execute("SELECT * FROM token_ledger ORDER BY rowid")]
        return user, ledger


def assert_cancelled(path):
    user, ledger = observe(path)
    assert user["token_balance"] == 500
    assert user["daily_tokens_used"] == user["openrouter_monthly_tokens_used"] == 0
    assert user["tokens_used"] == user["generation_count"] == 0
    assert sum(row["delta"] for row in ledger) == 0
    assert sum(row["reason"] in accounting.REFUNDS for row in ledger) == 1
    assert all(json.loads(row["meta_json"])["jobId"] == "fixture-job" for row in ledger)


@pytest.mark.parametrize("kind", ["balance", "daily", "mixed", "monthly"])
@pytest.mark.parametrize("order", [("cancel", "settle"), ("settle", "cancel")], ids=["cancel-first", "settle-first"])
def test_both_orders_restore_only_original_charge(owned_databases, kind, order):
    path = seed(owned_databases, kind)
    for action in order:
        transition(path, action)
    assert_cancelled(path)
    assert transition(path, "cancel") is False
    assert transition(path, "settle") == {"adjusted": False, "refund": 0, "actual": 40, "settled": 0}
    assert_cancelled(path)


@pytest.mark.parametrize("repeat", range(3))
@pytest.mark.parametrize("kind", ["balance", "daily", "mixed", "monthly"])
@pytest.mark.parametrize("actions", [("cancel", "cancel"), ("cancel", "settle")], ids=["two-refunds", "refund-settlement"])
def test_independent_wal_connections_serialize_refunds(owned_databases, kind, actions, repeat):
    path = seed(owned_databases, kind)
    barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(transition, path, action, barrier=barrier) for action in actions]
        results = [future.result(timeout=12) for future in futures]
    if actions == ("cancel", "cancel"):
        assert sorted(results) == [False, True]
    assert_cancelled(path)


@pytest.mark.parametrize("repeat", range(3))
def test_concurrent_adjustment_is_applied_once(owned_databases, repeat):
    path = seed(owned_databases)
    barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: transition(path, "settle", barrier=barrier), range(2)))
    assert sorted(result["adjusted"] for result in results) == [False, True]
    user, ledger = observe(path)
    assert user["token_balance"] == 460 and user["tokens_used"] == 40
    assert sum(row["reason"] == accounting.ADJUSTMENT for row in ledger) == 1


@pytest.mark.parametrize("active_transaction", [False, True])
def test_writer_acquired_before_accounting_read_and_caller_owns_rollback(owned_databases, active_transaction):
    path = seed(owned_databases)
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        if active_transaction:
            conn.execute("BEGIN")
        statements = []
        conn.set_trace_callback(statements.append)
        assert accounting.refund_generation_tokens(conn, "fixture-job", reason="fixture")
        first_read = next(i for i, sql in enumerate(statements) if sql.startswith("SELECT"))
        expected = "UPDATE token_ledger SET id = id WHERE 0" if active_transaction else "BEGIN IMMEDIATE"
        assert statements.index(expected) < first_read
        conn.rollback()
    user, ledger = observe(path)
    assert user["token_balance"] == 400 and len(ledger) == 1


def test_ledger_failure_rolls_back_balance_and_quota(owned_databases):
    path = seed(owned_databases, "mixed")
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        conn.set_authorizer(lambda action, table, *_: sqlite3.SQLITE_DENY
                            if action == sqlite3.SQLITE_INSERT and table == "token_ledger" else sqlite3.SQLITE_OK)
        with pytest.raises(sqlite3.DatabaseError), conn:
            accounting.refund_generation_tokens(conn, "fixture-job", reason="fixture")
    user, ledger = observe(path)
    assert user["token_balance"] == 460 and user["daily_tokens_used"] == 60
    assert user["tokens_used"] == 100 and user["generation_count"] == 1 and len(ledger) == 1


@pytest.mark.parametrize("kind", ["daily", "monthly"])
def test_old_charge_does_not_refund_a_new_period_allowance(owned_databases, kind):
    path = seed(owned_databases, kind, charged_at=datetime.now(timezone.utc) - timedelta(days=400))
    before, _ = observe(path)
    transition(path, "settle")
    transition(path, "cancel")
    after, _ = observe(path)
    assert after["daily_tokens_used"] == before["daily_tokens_used"]
    assert after["openrouter_monthly_tokens_used"] == before["openrouter_monthly_tokens_used"]
    assert after["token_balance"] == 500


def test_missing_charge_is_noop(owned_databases):
    path = seed(owned_databases)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.row_factory = sqlite3.Row
        assert accounting.refund_generation_tokens(conn, "other-job", reason="fixture") is False
        assert accounting.reconcile_openrouter_token_charge(conn, "other-job", 40)["adjusted"] is False
    assert observe(path)[0]["token_balance"] == 400


@pytest.mark.parametrize("metadata", [{}, {"balance_refund": 1}, {"balance_refund": 999, "refund_tokens": 999}])
def test_legacy_adjustment_cash_delta_is_authoritative(owned_databases, metadata):
    path = seed(owned_databases)
    transition(path, "settle")
    with closing(sqlite3.connect(path)) as conn, conn:
        # Another job's 100 consumed tokens must survive this cancellation.
        conn.execute("UPDATE users SET tokens_used = tokens_used + 100")
        meta = {"jobId": "fixture-job", **metadata}
        conn.execute("UPDATE token_ledger SET meta_json = ? WHERE reason = ?",
                     (json.dumps(meta, separators=(",", ":")), accounting.ADJUSTMENT))
    assert transition(path, "cancel") is True
    user, ledger = observe(path)
    assert user["token_balance"] == 500 and user["tokens_used"] == 100
    assert sum(row["delta"] for row in ledger) == 0
    assert ledger[-1]["delta"] == 40


@pytest.mark.parametrize("order", [("cancel", "settle"), ("settle", "cancel")], ids=["cancel-first", "settle-first"])
def test_compact_json_charge_refund_and_adjustment_are_recognized(owned_databases, order):
    path = seed(owned_databases)
    for action in order:
        with closing(sqlite3.connect(path)) as conn, conn:
            for rowid, raw in conn.execute("SELECT rowid, meta_json FROM token_ledger").fetchall():
                conn.execute("UPDATE token_ledger SET meta_json = ? WHERE rowid = ?",
                             (json.dumps(json.loads(raw), separators=(",", ":")), rowid))
        transition(path, action)
    assert_cancelled(path)
    assert transition(path, "cancel") is False
    assert transition(path, "settle")["settled"] == 0


def test_like_narrowing_never_confuses_another_parsed_job_id(owned_databases):
    path = seed(owned_databases)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.row_factory = sqlite3.Row
        assert accounting.refund_generation_tokens(conn, "fixture", reason="fixture") is False
        assert accounting.reconcile_openrouter_token_charge(conn, "fixture", 40)["adjusted"] is False
    assert observe(path)[0]["token_balance"] == 400
