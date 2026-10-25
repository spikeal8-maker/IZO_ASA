"""Durable, fail-closed provider dispatch receipts. Not wired to production routes.

Each helper owns a short SQLite writer transaction on a caller-provided connection.
A begun dispatch is forever unsafe to replay without authoritative reconciliation,
even if the originating job row has been removed. No external provider I/O or
ledger mutation happens inside this module.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
import sqlite3
import uuid
from typing import Literal

BLOCKING = frozenset({'NOT_SENT', 'DISPATCHING', 'ACCEPTED', 'RECONCILIATION_PENDING'})
TERMINAL = frozenset({'COMPLETED', 'REJECTED'})


class ReceiptConflict(RuntimeError):
    """The same intent key was reused with incompatible immutable identity."""


class OutcomeUnresolved(RuntimeError):
    """A possibly accepted paid request forbids another dispatch."""


class InvalidTransition(RuntimeError):
    """The requested transition lacks authoritative evidence or state."""


def install_scratch_schema(conn: sqlite3.Connection) -> None:
    """Standalone schema proof; production migration deliberately out of scope."""
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS provider_dispatch_receipts (
      id TEXT PRIMARY KEY,
      owner_id TEXT NOT NULL,
      command_key TEXT NOT NULL,
      payload_sha256 TEXT NOT NULL,
      provider TEXT NOT NULL,
      source_job_id TEXT,
      provider_job_id TEXT,
      state TEXT NOT NULL CHECK(state IN
        ('NOT_SENT','DISPATCHING','ACCEPTED','RECONCILIATION_PENDING','COMPLETED','REJECTED')),
      dispatch_attempts INTEGER NOT NULL DEFAULT 0 CHECK(dispatch_attempts BETWEEN 0 AND 1),
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE(owner_id,command_key)
    );
    CREATE INDEX IF NOT EXISTS idx_provider_receipt_owner_payload_state
      ON provider_dispatch_receipts(owner_id,payload_sha256,state);
    CREATE TABLE IF NOT EXISTS provider_dispatch_events (
      id TEXT PRIMARY KEY,
      receipt_id TEXT NOT NULL REFERENCES provider_dispatch_receipts(id),
      from_state TEXT,
      to_state TEXT NOT NULL,
      event_type TEXT NOT NULL,
      evidence_sha256 TEXT,
      operator_id TEXT,
      reason TEXT,
      created_at TEXT NOT NULL
    );
    ''')


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate(owner: str, key: str, fingerprint: str, provider: str) -> None:
    if not all(isinstance(v,str) and v and len(v)<=160 and not any(ord(c)<32 for c in v)
               for v in (owner,key,provider)):
        raise ValueError('INVALID_RECEIPT_IDENTITY')
    if not isinstance(key, str) or not 1 <= len(key) <= 128 or any(not 33 <= ord(c) <= 126 for c in key):
        raise ValueError('INVALID_IDEMPOTENCY_KEY')
    if not isinstance(fingerprint, str) or not re.fullmatch(r'[a-f0-9]{64}', fingerprint):
        raise ValueError('INVALID_PAYLOAD_SHA256')


def _event(conn: sqlite3.Connection, receipt_id: str, before: str | None,
           after: str, kind: str, evidence: str | None = None,
           operator: str | None = None, reason: str | None = None) -> None:
    conn.execute('INSERT INTO provider_dispatch_events VALUES (?,?,?,?,?,?,?,?,?)',
                 (str(uuid.uuid4()),receipt_id,before,after,kind,evidence,operator,reason,_now()))


def begin_intent(conn: sqlite3.Connection, *, owner: str, command_key: str,
                 payload_sha256: str, provider: str, job_id: str | None) -> tuple[str,str]:
    """Exactly one durable receipt for the owner/command. Return (id, current state).

    A fresh identical fingerprint under a DIFFERENT key is blocked while any
    previous intent for that owner remains unresolved. This protects unknown
    video outcomes without treating all matching prompts as permanently equal.
    """
    _validate(owner,command_key,payload_sha256,provider)
    conn.execute('BEGIN IMMEDIATE')
    try:
        existing = conn.execute('SELECT id,payload_sha256,provider,state FROM provider_dispatch_receipts '
                                'WHERE owner_id=? AND command_key=?',(owner,command_key)).fetchone()
        if existing:
            if existing[1]!=payload_sha256 or existing[2]!=provider:
                raise ReceiptConflict('KEY_PAYLOAD_OR_PROVIDER_MISMATCH')
            conn.commit()
            return existing[0],existing[3]
        row=conn.execute('SELECT id FROM provider_dispatch_receipts WHERE owner_id=? '
                         'AND payload_sha256=? AND state IN (?,?,?,?) LIMIT 1',
                         (owner,payload_sha256,*sorted(BLOCKING))).fetchone()
        if row:
            raise OutcomeUnresolved('UNRESOLVED_PROVIDER_REQUEST_FOR_OWNER_AND_PAYLOAD')
        receipt_id=str(uuid.uuid4());created=_now()
        conn.execute('INSERT INTO provider_dispatch_receipts '
                     '(id,owner_id,command_key,payload_sha256,provider,source_job_id,state,created_at,updated_at) '
                     'VALUES (?,?,?,?,?,?,?, ?,?)',
                     (receipt_id,owner,command_key,payload_sha256,provider,job_id,'NOT_SENT',created,created))
        _event(conn,receipt_id,None,'NOT_SENT','INTENT_RESERVED')
        conn.commit()
        return receipt_id,'NOT_SENT'
    except BaseException:
        conn.rollback()
        raise


def acquire_dispatch(conn: sqlite3.Connection, receipt_id: str) -> bool:
    """Durably fence a send BEFORE any external HTTP. A crash is ambiguous, not retryable."""
    conn.execute('BEGIN IMMEDIATE')
    try:
        changed=conn.execute("UPDATE provider_dispatch_receipts SET state='DISPATCHING', "
                             "dispatch_attempts=1,updated_at=? WHERE id=? AND state='NOT_SENT' "
                             'AND dispatch_attempts=0',(_now(),receipt_id)).rowcount
        if changed:
            _event(conn,receipt_id,'NOT_SENT','DISPATCHING','SEND_FENCED')
        conn.commit()
        return bool(changed)
    except BaseException:
        conn.rollback()
        raise


def acknowledge(conn: sqlite3.Connection, receipt_id: str,
                outcome: Literal['ACCEPTED','OUTCOME_UNKNOWN','ACK_REJECTED'],
                *, provider_job_id: str | None = None, evidence_sha256: str | None = None) -> str:
    """ACK_REJECTED must be a proven non-execution; errors/timeouts stay UNKNOWN."""
    target={'ACCEPTED':'ACCEPTED','OUTCOME_UNKNOWN':'RECONCILIATION_PENDING','ACK_REJECTED':'REJECTED'}[outcome]
    if outcome!='OUTCOME_UNKNOWN' and not (evidence_sha256 and re.fullmatch(r'[a-f0-9]{64}',evidence_sha256)):
        raise InvalidTransition('AUTHORITATIVE_PROVIDER_RECEIPT_REQUIRED')
    conn.execute('BEGIN IMMEDIATE')
    try:
        row=conn.execute('SELECT state FROM provider_dispatch_receipts WHERE id=?',(receipt_id,)).fetchone()
        if row is None or row[0] not in ('DISPATCHING','ACCEPTED'):
            raise InvalidTransition('ACK_OUTSIDE_DISPATCH_LIFECYCLE')
        if row[0]=='ACCEPTED' and outcome!='OUTCOME_UNKNOWN':
            raise InvalidTransition('ACCEPTED_PROVIDER_ALREADY_FENCED')
        conn.execute('UPDATE provider_dispatch_receipts SET state=?, '
                     'provider_job_id=COALESCE(provider_job_id,?), updated_at=? WHERE id=?',
                     (target,provider_job_id,_now(),receipt_id))
        _event(conn,receipt_id,row[0],target,outcome,evidence_sha256)
        conn.commit()
        return target
    except BaseException:
        conn.rollback()
        raise


def resolve(conn: sqlite3.Connection, receipt_id: str,
            final: Literal['COMPLETED','REJECTED'], *, evidence_sha256: str,
            operator_id: str, reason: str) -> str:
    """Explicit attested provider/manual reconciliation; no time-based unlock."""
    if (not isinstance(evidence_sha256,str) or not re.fullmatch(r'[a-f0-9]{64}',evidence_sha256)
            or not isinstance(operator_id,str) or not operator_id.strip()
            or not isinstance(reason,str) or not reason.strip()):
        raise InvalidTransition('OPERATOR_AND_AUTHORITATIVE_EVIDENCE_REQUIRED')
    conn.execute('BEGIN IMMEDIATE')
    try:
        row=conn.execute('SELECT state FROM provider_dispatch_receipts WHERE id=?',(receipt_id,)).fetchone()
        if row is None or row[0] not in ('RECONCILIATION_PENDING','ACCEPTED'):
            raise InvalidTransition('NOT_PENDING_RECONCILIATION')
        conn.execute('UPDATE provider_dispatch_receipts SET state=?,updated_at=? WHERE id=?',
                     (final,_now(),receipt_id))
        _event(conn,receipt_id,row[0],final,'OPERATOR_RECONCILED',evidence_sha256,operator_id,reason)
        conn.commit()
        return final
    except BaseException:
        conn.rollback()
        raise


def can_attempt_compatible_fallback(state: str) -> bool:
    """Only no-send or PROVEN non-execution; separate tariff/model preflight is mandatory."""
    return state in ('NOT_SENT','REJECTED')
