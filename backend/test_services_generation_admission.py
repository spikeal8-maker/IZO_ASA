from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest

from app.services.generation_admission import (
    IdempotencyConflict,
    admit_generation,
    generation_request_fingerprint,
    lookup_generation_admission,
)


SCHEMA = """
CREATE TABLE users (id TEXT PRIMARY KEY, balance INTEGER NOT NULL);
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL
);
CREATE TABLE ledger (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    job_id TEXT NOT NULL REFERENCES jobs(id),
    kind TEXT NOT NULL,
    amount INTEGER NOT NULL,
    UNIQUE(job_id, kind)
);
CREATE TABLE generation_admissions (
    user_id TEXT NOT NULL REFERENCES users(id),
    idempotency_key TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id),
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(user_id, idempotency_key)
);
INSERT INTO users VALUES ('alice', 10), ('bob', 10);
"""
REQUEST = {"mode": "txt2img", "prompt": "Река", "steps": 4, "seed": None}


def connect(path: Path, *, isolation_level: str | None = "", timeout: float = 5):
    conn = sqlite3.connect(path, isolation_level=isolation_level, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "admission.sqlite3"
    with closing(connect(path)) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
    return path


def create_job(conn, user_id="alice"):
    job_id = "job_" + uuid4().hex
    conn.execute("INSERT INTO jobs VALUES (?, ?, 'queued')", (job_id, user_id))
    updated = conn.execute(
        "UPDATE users SET balance = balance - 3 WHERE id = ? AND balance >= 3",
        (user_id,),
    )
    if updated.rowcount != 1:
        raise ValueError("Insufficient tokens")
    conn.execute(
        "INSERT INTO ledger (user_id, job_id, kind, amount) VALUES (?, ?, 'generation', -3)",
        (user_id, job_id),
    )
    return job_id, {"id": job_id, "userId": user_id, "status": "queued", "seed": 42}


def admission(conn, *, user="alice", key="operation-key", request=None, callback=None):
    return admit_generation(
        conn,
        trusted_user_id=user,
        idempotency_key=key,
        normalized_request=REQUEST if request is None else request,
        create_job_and_accounting=callback or (lambda active: create_job(active, user)),
    )


def counts(conn):
    return tuple(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                 for table in ("generation_admissions", "jobs", "ledger"))


def balance(conn, user="alice"):
    return conn.execute("SELECT balance FROM users WHERE id = ?", (user,)).fetchone()[0]


def forbidden_callback(conn):
    raise AssertionError("Replay or rejection must not invoke the creation callback")


def test_fingerprint_canonical_order_preserves_content():
    left = {"b": {"y": True, "x": None}, "a": ["Кот", 4]}
    right = {"a": ["Кот", 4], "b": {"x": None, "y": True}}
    assert generation_request_fingerprint(left) == generation_request_fingerprint(right)
    assert generation_request_fingerprint(left) != generation_request_fingerprint(
        {"b": left["b"], "a": [4, "Кот"]}
    )


@pytest.mark.parametrize("payload", [
    {"value": float("nan")}, {"value": float("inf")}, {"value": object()},
    {"nested": {1: "bad"}}, {"nested": [dict([(None, "bad")])]},
])
def test_invalid_json_fails_before_transaction(database, payload):
    with closing(connect(database)) as conn:
        with pytest.raises((TypeError, ValueError)):
            admission(conn, request=payload, callback=forbidden_callback)
        assert not conn.in_transaction
        assert counts(conn) == (0, 0, 0)


@pytest.mark.parametrize("key", ["", " ", "has space", "line\nbreak", "ключ", "x" * 201, None])
def test_invalid_keys_fail_before_transaction(database, key):
    with closing(connect(database)) as conn:
        with pytest.raises(ValueError, match="Idempotency-Key"):
            admission(conn, key=key, callback=forbidden_callback)
        assert not conn.in_transaction


@pytest.mark.parametrize("user", ["", "  ", None])
def test_trusted_identity_is_required(database, user):
    with closing(connect(database)) as conn:
        with pytest.raises(ValueError, match="trusted user"):
            admission(conn, user=user, callback=forbidden_callback)
        assert not conn.in_transaction


@pytest.mark.parametrize("isolation_level", ["", None])
def test_atomic_receipt_and_caller_commit(database, isolation_level):
    with closing(connect(database, isolation_level=isolation_level)) as conn:
        with closing(connect(database)) as observer:
            result = admission(conn)
            assert result.created
            assert conn.in_transaction
            assert counts(conn) == (1, 1, 1)
            assert balance(conn) == 7
            assert counts(observer) == (0, 0, 0)
            assert balance(observer) == 10
            conn.commit()
            assert counts(observer) == (1, 1, 1)
            assert balance(observer) == 7


def test_replay_is_durable_after_reconnect_and_keeps_original_response(database):
    with closing(connect(database)) as conn:
        first = admission(conn)
        conn.commit()
        conn.execute("UPDATE jobs SET status = 'completed' WHERE id = ?", (first.job_id,))
        conn.execute("UPDATE generation_admissions SET created_at = '1970-01-01T00:00:00Z'")
        conn.commit()
    with closing(connect(database)) as conn:
        replay = admission(conn, callback=forbidden_callback)
        assert not replay.created
        assert replay.job_id == first.job_id
        assert replay.response == first.response
        assert replay.response["status"] == "queued"
        assert conn.execute("SELECT status FROM jobs WHERE id = ?", (replay.job_id,)).fetchone()[0] == "completed"
        assert counts(conn) == (1, 1, 1)
        conn.commit()


def test_changed_payload_conflicts_without_new_job_or_charge(database):
    with closing(connect(database)) as conn:
        admission(conn)
        conn.commit()
        with pytest.raises(IdempotencyConflict):
            admission(conn, request={**REQUEST, "prompt": "Горы"}, callback=forbidden_callback)
        conn.rollback()
        assert counts(conn) == (1, 1, 1)
        assert balance(conn) == 7


def test_same_key_is_scoped_by_trusted_user(database):
    with closing(connect(database)) as conn:
        first = admission(conn)
        conn.commit()
        other = admission(conn, user="bob")
        conn.commit()
        assert other.created and other.job_id != first.job_id
        assert counts(conn) == (2, 2, 2)
        assert balance(conn, "alice") == balance(conn, "bob") == 7


def test_callback_failure_rolls_back_job_charge_and_receipt(database):
    def fail(conn):
        create_job(conn)
        raise RuntimeError("interrupted after debit")
    with closing(connect(database)) as conn:
        with pytest.raises(RuntimeError, match="after debit"):
            admission(conn, callback=fail)
        assert conn.in_transaction
        assert counts(conn) == (0, 0, 0)
        assert balance(conn) == 10
        conn.rollback()
        assert admission(conn).created
        conn.commit()
        assert counts(conn) == (1, 1, 1)


@pytest.mark.parametrize("bad_result", ["missing-job", "wrong-owner", "invalid-json"])
def test_invalid_callback_result_rolls_back_all_its_writes(database, bad_result):
    def invalid(conn):
        job_id, response = create_job(conn, "bob" if bad_result == "wrong-owner" else "alice")
        if bad_result == "missing-job":
            return "absent", response
        if bad_result == "invalid-json":
            response["usage"] = float("nan")
        return job_id, response
    with closing(connect(database)) as conn:
        with pytest.raises(ValueError):
            admission(conn, callback=invalid)
        assert counts(conn) == (0, 0, 0)
        assert balance(conn, "alice") == balance(conn, "bob") == 10
        conn.rollback()


def test_receipt_insert_failure_rolls_back_only_new_callback_writes(database):
    with closing(connect(database)) as conn:
        first = admission(conn)
        conn.commit()
        def duplicate_job(active):
            active.execute("UPDATE users SET balance = balance - 1 WHERE id = 'alice'")
            return first.job_id, first.response
        with pytest.raises(sqlite3.IntegrityError):
            admission(conn, key="different-key", callback=duplicate_job)
        assert balance(conn) == 7
        assert counts(conn) == (1, 1, 1)
        conn.rollback()


def test_savepoint_preserves_prior_caller_work_without_committing_it(database):
    with closing(connect(database)) as conn:
        conn.execute("UPDATE users SET balance = balance + 2 WHERE id = 'bob'")
        def fail(active):
            create_job(active)
            raise RuntimeError("callback failed")
        with pytest.raises(RuntimeError):
            admission(conn, callback=fail)
        assert balance(conn, "bob") == 12
        assert counts(conn) == (0, 0, 0)
        with closing(connect(database)) as observer:
            assert balance(observer, "bob") == 10
        conn.rollback()
        assert balance(conn, "bob") == 10


def test_caller_rollback_removes_entire_admission_and_allows_retry(database):
    with closing(connect(database)) as conn:
        uncommitted = admission(conn)
        conn.rollback()
        assert counts(conn) == (0, 0, 0)
        assert balance(conn) == 10
        retry = admission(conn)
        assert retry.created and retry.job_id != uncommitted.job_id
        conn.commit()
        assert counts(conn) == (1, 1, 1)


@pytest.mark.parametrize("prior_write", [False, True])
def test_existing_read_or_write_transaction_is_upgraded_and_remains_owned(database, prior_write):
    with closing(connect(database)) as conn:
        conn.execute("BEGIN")
        conn.execute("SELECT balance FROM users").fetchall()
        if prior_write:
            conn.execute("UPDATE users SET balance = balance + 1 WHERE id = 'bob'")
        assert admission(conn).created
        assert conn.in_transaction
        conn.rollback()
        assert counts(conn) == (0, 0, 0)
        assert balance(conn, "bob") == 10


def test_zero_row_upgrade_does_not_update_receipts_or_fire_triggers(database):
    with closing(connect(database)) as conn:
        admission(conn)
        conn.commit()
        conn.executescript("""
            CREATE TABLE upgrade_audit (called INTEGER);
            CREATE TRIGGER admission_updated AFTER UPDATE ON generation_admissions
            BEGIN INSERT INTO upgrade_audit VALUES (1); END;
        """)
        conn.execute("BEGIN")
        conn.execute("SELECT * FROM generation_admissions").fetchall()
        before = conn.total_changes
        assert not admission(conn, callback=forbidden_callback).created
        assert conn.total_changes == before
        assert conn.execute("SELECT COUNT(*) FROM upgrade_audit").fetchone()[0] == 0
        conn.rollback()


def test_held_writer_fails_before_callback(database):
    with closing(connect(database)) as writer, closing(connect(database, timeout=0.01)) as conn:
        writer.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            admission(conn, callback=forbidden_callback)
        assert not conn.in_transaction
        writer.rollback()
        assert counts(conn) == (0, 0, 0)


def test_stale_wal_snapshot_fails_closed_before_callback(database):
    with closing(connect(database)) as stale, closing(connect(database)) as writer:
        stale.execute("BEGIN")
        stale.execute("SELECT balance FROM users").fetchall()
        admission(writer)
        writer.commit()
        with pytest.raises(sqlite3.OperationalError, match="locked") as caught:
            admission(stale, key="stale-key", callback=forbidden_callback)
        assert caught.value.sqlite_errorcode == sqlite3.SQLITE_BUSY_SNAPSHOT
        assert stale.in_transaction
        stale.rollback()
        assert counts(stale) == (1, 1, 1)
        assert balance(stale) == 7


def test_migration_is_required_and_not_created_at_runtime():
    with closing(sqlite3.connect(":memory:")) as conn:
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            admission(conn, callback=forbidden_callback)
        conn.rollback()
        assert conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall() == []

def test_early_lookup_is_read_only_and_validates_existing_fingerprint(database):
    with closing(connect(database)) as conn:
        args = dict(trusted_user_id="alice", idempotency_key="operation-key", normalized_request=REQUEST)
        before = conn.total_changes
        assert lookup_generation_admission(conn, **args) is None
        assert not conn.in_transaction and conn.total_changes == before
        created = admission(conn)
        conn.commit()
        before = conn.total_changes
        replay = lookup_generation_admission(conn, **args)
        assert replay.job_id == created.job_id and not replay.created
        assert replay.response == created.response
        with pytest.raises(IdempotencyConflict):
            lookup_generation_admission(conn, **{**args, "normalized_request": {"prompt": "changed"}})
        assert not conn.in_transaction and conn.total_changes == before


def test_admission_rechecks_after_an_early_lookup_miss(database):
    args = dict(trusted_user_id="alice", idempotency_key="operation-key", normalized_request=REQUEST)
    with closing(connect(database)) as reader:
        assert lookup_generation_admission(reader, **args) is None
    with closing(connect(database)) as winner:
        created = admission(winner)
        winner.commit()
    with closing(connect(database)) as contender:
        replay = admission(contender, callback=forbidden_callback)
        contender.commit()
        assert replay.job_id == created.job_id and not replay.created
        assert counts(contender) == (1, 1, 1)


def test_early_lookup_does_not_acquire_a_writer_lock(database):
    with closing(connect(database)) as writer, closing(connect(database, timeout=0.01)) as reader:
        created = admission(writer)
        writer.commit()
        writer.execute("BEGIN IMMEDIATE")
        replay = lookup_generation_admission(
            reader, trusted_user_id="alice", idempotency_key="operation-key", normalized_request=REQUEST,
        )
        assert replay.job_id == created.job_id and not reader.in_transaction
        writer.rollback()
