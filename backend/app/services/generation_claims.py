"""Owned generation claims and caller-transaction fences, without schema changes.

The in-process queue remains a wake-up mechanism. This module does not provide
leases, cross-process scheduling, or atomic rollback of filesystem/provider work.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import sqlite3
import threading
import uuid

from .generation_worker import GenerationClaimLost


METADATA_KEY = "_workerClaim"
ACTIVE = frozenset({"queued", "running", "uploading", "sent_to_comfyui", "sent_to_openrouter"})
TERMINAL = frozenset({"completed", "failed", "cancelled"})


@dataclass(frozen=True)
class Claim:
    job_id: str
    user_id: str
    token: str


@dataclass
class _Transaction:
    connection: object
    thread_id: int
    after_commit: list = field(default_factory=list)
    failed: bool = False


_claim = ContextVar("generation_worker_claim", default=None)
_transaction = ContextVar("generation_worker_transaction", default=None)
_cancellation = ContextVar("generation_authorized_cancellation", default=None)


def _writer(conn) -> None:
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    else:
        conn.execute("UPDATE jobs SET id = id WHERE 0")


def _row(conn, job_id):
    return conn.execute("SELECT id,user_id,status,settings_json FROM jobs WHERE id = ?", (job_id,)).fetchone()


def _settings(row) -> dict:
    try:
        value = json.loads(row["settings_json"] or "{}")
    except (ValueError, TypeError):
        raise GenerationClaimLost("GENERATION_CLAIM_SETTINGS_INVALID") from None
    if not isinstance(value, dict):
        raise GenerationClaimLost("GENERATION_CLAIM_SETTINGS_INVALID")
    return value


def _owned(conn, claim: Claim):
    _writer(conn)
    row = _row(conn, claim.job_id)
    if row is None or row["user_id"] != claim.user_id or row["status"] not in ACTIVE - {"queued"}:
        raise GenerationClaimLost("GENERATION_CLAIM_LOST")
    if _settings(row).get(METADATA_KEY) != {"version": 1, "token": claim.token}:
        raise GenerationClaimLost("GENERATION_CLAIM_LOST")
    return row


def check_persist(conn, job_id: str, status: str) -> None:
    """Called before every shared jobs UPSERT and trial settlement."""
    _writer(conn)
    row = _row(conn, job_id)
    cancellation = _cancellation.get()
    raw = conn._transaction.connection if isinstance(conn, _BorrowedConnection) else conn
    if cancellation is not None and cancellation == (raw, job_id, row["user_id"] if row else None):
        if status != "cancelled" or row["status"] not in ACTIVE:
            raise GenerationClaimLost("GENERATION_CANCEL_STATE_CHANGED")
        return
    claim = _claim.get()
    if claim is not None:
        if claim.job_id != job_id or status not in ACTIVE | TERMINAL or status == "queued":
            raise GenerationClaimLost("GENERATION_CLAIM_LOST")
        _owned(conn, claim)
    elif row is not None and METADATA_KEY in _settings(row):
        raise GenerationClaimLost("GENERATION_CLAIM_REQUIRED")


@contextmanager
def claim_job(connect, job_id: str, user_id: str, *, now_iso: str):
    """Claim queued -> running once; release the writer before provider work."""
    if _claim.get() is not None:
        raise GenerationClaimLost("GENERATION_NESTED_CLAIM")
    claim = None
    with closing(connect()) as conn, conn:
        _writer(conn)
        row = _row(conn, job_id)
        if row is not None and row["user_id"] == user_id and row["status"] == "queued":
            settings = _settings(row)
            if METADATA_KEY not in settings:
                claim = Claim(job_id, user_id, uuid.uuid4().hex)
                settings[METADATA_KEY] = {"version": 1, "token": claim.token}
                updated = conn.execute(
                    "UPDATE jobs SET status='running',started_at=COALESCE(started_at,?),settings_json=? "
                    "WHERE id=? AND status='queued'",
                    (now_iso, json.dumps(settings, ensure_ascii=False), job_id),
                )
                if updated.rowcount != 1:
                    raise GenerationClaimLost("GENERATION_CLAIM_LOST")
    marker = _claim.set(claim)
    try:
        yield claim is not None
    finally:
        _claim.reset(marker)


class _BorrowedCursor:
    def __init__(self, connection, cursor):
        self.connection, self._cursor = connection, cursor

    def execute(self, *args):
        self._cursor.execute(*args)
        return self

    def executemany(self, *args):
        self._cursor.executemany(*args)
        return self

    def executescript(self, *_args):
        raise RuntimeError("GENERATION_IMPLICIT_COMMIT_FORBIDDEN")

    def __iter__(self):
        return iter(self._cursor)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _BorrowedConnection:
    def __init__(self, transaction):
        self._transaction = transaction

    def __enter__(self):
        return self

    def __exit__(self, error_type, _error, _traceback):
        if error_type is not None:
            self._transaction.failed = True

    def execute(self, *args):
        return _BorrowedCursor(self, self._transaction.connection.execute(*args))

    def executemany(self, *args):
        return _BorrowedCursor(self, self._transaction.connection.executemany(*args))

    def cursor(self, *args, **kwargs):
        return _BorrowedCursor(self, self._transaction.connection.cursor(*args, **kwargs))

    def commit(self):
        self._transaction.failed = True
        raise RuntimeError("GENERATION_NESTED_COMMIT_FORBIDDEN")

    def rollback(self):
        self._transaction.failed = True
        raise RuntimeError("GENERATION_NESTED_ROLLBACK_FORBIDDEN")

    def executescript(self, *_args):
        self._transaction.failed = True
        raise RuntimeError("GENERATION_IMPLICIT_COMMIT_FORBIDDEN")

    def close(self):
        pass  # The outer owner closes its connection after commit/rollback.

    def __getattr__(self, name):
        return getattr(self._transaction.connection, name)


def connection(open_connection):
    """Join only the bound finalization; ordinary db() callers stay unchanged."""
    transaction = _transaction.get()
    if transaction is None:
        return open_connection()
    if threading.get_ident() != transaction.thread_id:
        raise RuntimeError("GENERATION_TRANSACTION_THREAD_MISMATCH")
    return _BorrowedConnection(transaction)


@contextmanager
def transaction(connect):
    """Fence and commit local finalization together, with no provider await."""
    claim = _claim.get()
    if claim is None:
        yield None
        return
    if _transaction.get() is not None:
        with connection(connect) as conn:
            yield conn
        return
    with closing(connect()) as conn:
        bound = _Transaction(conn, threading.get_ident())
        with conn:
            _owned(conn, claim)
            def authorize(action, _arg1, _arg2, _database, _trigger):
                if action == sqlite3.SQLITE_TRANSACTION:
                    bound.failed = True
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            conn.set_authorizer(authorize)
            marker = _transaction.set(bound)
            try:
                yield _BorrowedConnection(bound)
                if bound.failed:
                    raise RuntimeError("GENERATION_NESTED_TRANSACTION_FAILED")
            finally:
                _transaction.reset(marker)
                conn.set_authorizer(None)
        for callback in bound.after_commit:
            callback()


def after_commit(callback) -> None:
    transaction = _transaction.get()
    if transaction is None:
        callback()
    else:
        transaction.after_commit.append(callback)


@contextmanager
def authorize_cancellation(conn, job_id: str, user_id: str):
    """Trusted route authorization, tied to its locked connection and owner."""
    _writer(conn)
    row = _row(conn, job_id)
    if row is None or row["user_id"] != user_id:
        raise LookupError("GENERATION_JOB_NOT_FOUND")
    marker = _cancellation.set((conn, job_id, user_id))
    try:
        yield row
    finally:
        _cancellation.reset(marker)


def can_recover_media(conn, job_id: str) -> bool:
    """Legacy missing-row repair must never revive a known unfinished job."""
    row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return row is None or row["status"] == "completed"
