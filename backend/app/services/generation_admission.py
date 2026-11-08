"""Durable generation admission inside a caller-owned SQLite transaction.

The caller supplies a server-authenticated user and an already normalized request.
The callback must create the job and its accounting using the supplied connection.
It must not commit, roll back, execute scripts, enqueue work or perform external I/O.
Commit one admission before enqueueing only a newly created job. On any exception,
the caller must roll back before reusing the connection. No runtime schema creation
or implicit retry is performed here.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


MAX_IDEMPOTENCY_KEY_LENGTH = 200


class IdempotencyConflict(Exception):
    """The authenticated user already used this key for a different request."""


@dataclass(frozen=True)
class GenerationAdmissionResult:
    created: bool
    job_id: str
    response: dict[str, Any]
    request_fingerprint: str


def _validate_json_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            _validate_json_keys(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _validate_json_keys(child)


def _canonical_object(value: Mapping[str, Any]) -> str:
    if not isinstance(value, Mapping):
        raise TypeError("Expected a normalized JSON object")
    _validate_json_keys(value)
    return json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    )


def generation_request_fingerprint(normalized_request: Mapping[str, Any]) -> str:
    """Hash normalized JSON; random seeds and timestamps belong in the callback."""
    return hashlib.sha256(_canonical_object(normalized_request).encode("utf-8")).hexdigest()


def _validate_identity(trusted_user_id: str, idempotency_key: str) -> None:
    if not isinstance(trusted_user_id, str) or not trusted_user_id.strip():
        raise ValueError("A trusted user id is required")
    if (
        not isinstance(idempotency_key, str)
        or not 1 <= len(idempotency_key) <= MAX_IDEMPOTENCY_KEY_LENGTH
        or any(ord(char) < 33 or ord(char) > 126 for char in idempotency_key)
    ):
        raise ValueError("Idempotency-Key must contain 1 to 200 visible ASCII characters")


def _lookup_receipt(
    conn: sqlite3.Connection, user_id: str, key: str, fingerprint: str,
) -> GenerationAdmissionResult | None:
    row = conn.execute(
        "SELECT request_fingerprint, job_id, response_json "
        "FROM generation_admissions WHERE user_id = ? AND idempotency_key = ?",
        (user_id, key),
    ).fetchone()
    if row is None:
        return None
    if row[0] != fingerprint:
        raise IdempotencyConflict(
            "Idempotency-Key is already used for a different generation request"
        )
    response = json.loads(row[2])
    if not isinstance(response, dict):
        raise ValueError("Stored generation admission response must be an object")
    return GenerationAdmissionResult(False, row[1], response, fingerprint)


def lookup_generation_admission(
    conn: sqlite3.Connection,
    *,
    trusted_user_id: str,
    idempotency_key: str,
    normalized_request: Mapping[str, Any],
) -> GenerationAdmissionResult | None:
    """Read a receipt before tariff/rate-limit/provider revalidation.

    This performs no writes or transaction management. Close a separate early-read
    connection before admission to avoid carrying a stale WAL snapshot forward.
    A miss is advisory: admit_generation must recheck under its write reservation.
    """
    _validate_identity(trusted_user_id, idempotency_key)
    fingerprint = generation_request_fingerprint(normalized_request)
    return _lookup_receipt(conn, trusted_user_id, idempotency_key, fingerprint)


def admit_generation(
    conn: sqlite3.Connection,
    *,
    trusted_user_id: str,
    idempotency_key: str,
    normalized_request: Mapping[str, Any],
    create_job_and_accounting: Callable[
        [sqlite3.Connection], tuple[str, Mapping[str, Any]]
    ],
) -> GenerationAdmissionResult:
    """Create or replay an admission without committing the caller's transaction.

    A fresh connection gets BEGIN IMMEDIATE, including isolation_level=None.
    An existing transaction is upgraded by a zero-row write before receipt reads.
    A busy writer or stale WAL snapshot propagates before callback execution.
    Savepoints roll back this admission's writes on callback/receipt failures while
    preserving earlier caller writes. The outer transaction and its write lock
    remain caller-owned on both success and failure.

    The response is the original admission response. Callers may fetch the current
    persisted status using job_id and trusted_user_id after commit; a replay must
    never re-run the callback or enqueue the job.
    """
    _validate_identity(trusted_user_id, idempotency_key)
    fingerprint = generation_request_fingerprint(normalized_request)
    if conn.in_transaction:
        conn.execute("UPDATE generation_admissions SET job_id = job_id WHERE 0")
    else:
        conn.execute("BEGIN IMMEDIATE")

    savepoint = "generation_admission_" + uuid4().hex
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        result = _lookup_receipt(conn, trusted_user_id, idempotency_key, fingerprint)
        if result is None:
            job_id, response = create_job_and_accounting(conn)
            if not isinstance(job_id, str) or not job_id:
                raise ValueError("Generation callback must return a persisted job id")
            job = conn.execute(
                "SELECT user_id FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if job is None or job[0] != trusted_user_id:
                raise ValueError("Generation callback must persist a job owned by its trusted user")
            response_json = _canonical_object(response)
            conn.execute(
                "INSERT INTO generation_admissions "
                "(user_id, idempotency_key, request_fingerprint, job_id, response_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    trusted_user_id, idempotency_key, fingerprint, job_id, response_json,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            result = GenerationAdmissionResult(
                True, job_id, json.loads(response_json), fingerprint
            )
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        return result
    except BaseException:
        if conn.in_transaction:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise
