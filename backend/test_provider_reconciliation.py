"""Synthetic durable receipt tests: no production service, keys, provider or money."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import pytest

from app.services.provider_reconciliation import (
    InvalidTransition, ReceiptConflict, OutcomeUnresolved,
    acknowledge, acquire_dispatch, begin_intent, can_attempt_compatible_fallback,
    install_scratch_schema, resolve,
)

FP=hashlib.sha256(b'synthetic payload').hexdigest()
PROOF=hashlib.sha256(b'fake-authoritative-provider-response').hexdigest()


def connect(path):
    conn=sqlite3.connect(path,timeout=5)
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def db(tmp_path):
    path=tmp_path/'standalone.sqlite'
    with connect(path) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        install_scratch_schema(conn)
    return path


def register(path,owner='A',key='intent-1',fp=FP):
    with connect(path) as conn:
        return begin_intent(conn,owner=owner,command_key=key,payload_sha256=fp,
                            provider='synthetic-provider',job_id='job_1')


@pytest.mark.parametrize('duplicates',[2,5,10])
def test_same_key_concurrent_one_receipt_and_fenced_send(tmp_path,duplicates):
    path=db(tmp_path)
    with ThreadPoolExecutor(max_workers=duplicates) as pool:
        pairs=list(pool.map(lambda _:register(path),range(duplicates)))
    assert len({p[0] for p in pairs})==1
    with ThreadPoolExecutor(max_workers=duplicates) as pool:
        wins=list(pool.map(lambda _:begin_send(path,pairs[0][0]),range(duplicates)))
    assert sum(wins)==1
    with connect(path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM provider_dispatch_receipts').fetchone()[0]==1
        assert conn.execute('SELECT dispatch_attempts FROM provider_dispatch_receipts').fetchone()[0]==1
        assert conn.execute("SELECT COUNT(*) FROM provider_dispatch_events WHERE event_type='SEND_FENCED'").fetchone()[0]==1


def begin_send(path,receipt):
    with connect(path) as conn:return acquire_dispatch(conn,receipt)


def test_changed_payload_conflicts_and_other_account_is_independent(tmp_path):
    path=db(tmp_path)
    receipt,_=register(path)
    with pytest.raises(ReceiptConflict):register(path,fp=hashlib.sha256(b'altered').hexdigest())
    independent,_=register(path,owner='B')
    assert independent!=receipt
    with pytest.raises(OutcomeUnresolved):register(path,key='other-intent')


def test_unknown_outcome_survives_job_deletion_and_process_restart(tmp_path):
    path=db(tmp_path)
    receipt,_=register(path)
    assert begin_send(path,receipt)
    with connect(path) as conn:
        assert acknowledge(conn,receipt,'OUTCOME_UNKNOWN')=='RECONCILIATION_PENDING'
    # No job FK/cascade: archival removal cannot silently unlock a second paid intent.
    with connect(path) as conn:
        conn.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY)')
        conn.execute('INSERT INTO jobs VALUES (?)',('job_1',))
        conn.execute('DELETE FROM jobs WHERE id=?',('job_1',))
    assert not can_attempt_compatible_fallback('RECONCILIATION_PENDING')
    with pytest.raises(OutcomeUnresolved):register(path,key='second-intent')
    with connect(path) as conn:
        assert conn.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        assert conn.execute('SELECT state FROM provider_dispatch_receipts').fetchone()[0]=='RECONCILIATION_PENDING'
        with pytest.raises(InvalidTransition):resolve(conn,receipt,'REJECTED',evidence_sha256='',operator_id='QA',reason='guess')
        assert resolve(conn,receipt,'COMPLETED',evidence_sha256=PROOF,operator_id='synthetic-operator',reason='matched provider receipt')=='COMPLETED'
    assert register(path,key='second-intent')[1]=='NOT_SENT'


def test_accepted_lost_ack_late_completion_and_operator_audit(tmp_path):
    path=db(tmp_path)
    receipt,_=register(path)
    assert begin_send(path,receipt)
    with connect(path) as conn:
        assert acknowledge(conn,receipt,'ACCEPTED',provider_job_id='provider-job-1',evidence_sha256=PROOF)=='ACCEPTED'
        assert acknowledge(conn,receipt,'OUTCOME_UNKNOWN')=='RECONCILIATION_PENDING'
    with pytest.raises(OutcomeUnresolved):register(path,key='new-key')
    with connect(path) as conn:
        assert resolve(conn,receipt,'COMPLETED',evidence_sha256=PROOF,operator_id='operator-A',reason='late provider terminal callback')=='COMPLETED'
        assert conn.execute("SELECT COUNT(*) FROM provider_dispatch_events WHERE event_type='OPERATOR_RECONCILED'").fetchone()[0]==1
        assert conn.execute('SELECT dispatch_attempts FROM provider_dispatch_receipts').fetchone()[0]==1


def test_ack_rejected_requires_proof_and_stops_replay(tmp_path):
    path=db(tmp_path)
    receipt,_=register(path)
    assert begin_send(path,receipt)
    with connect(path) as conn:
        with pytest.raises(InvalidTransition):acknowledge(conn,receipt,'ACK_REJECTED')
        assert acknowledge(conn,receipt,'ACK_REJECTED',evidence_sha256=PROOF)=='REJECTED'
    assert can_attempt_compatible_fallback('REJECTED')
    assert register(path,key='new-after-definitive-rejection')[1]=='NOT_SENT'


def test_unknown_never_enables_fallback_or_second_send(tmp_path):
    path=db(tmp_path);receipt,_=register(path)
    assert begin_send(path,receipt)
    with connect(path) as conn:
        acknowledge(conn,receipt,'OUTCOME_UNKNOWN')
        assert conn.execute('SELECT dispatch_attempts FROM provider_dispatch_receipts').fetchone()[0]==1
    assert not begin_send(path,receipt)
    for state in ('DISPATCHING','ACCEPTED','RECONCILIATION_PENDING','COMPLETED'):
        assert not can_attempt_compatible_fallback(state)
    assert can_attempt_compatible_fallback('NOT_SENT')


def test_reject_malformed_key_and_unknown_evidence_before_any_receipt(tmp_path):
    path=db(tmp_path)
    for key in ('', 'x' * 129, 'contains space', 'кириллица', 'line\nbreak'):
        with pytest.raises(ValueError):register(path,key=key)
    with pytest.raises(ValueError):register(path,fp='not-a-sha256')
    with connect(path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM provider_dispatch_receipts').fetchone()[0]==0


def test_operator_id_and_reason_must_be_verified_by_caller(tmp_path):
    path=db(tmp_path);receipt,_=register(path)
    assert begin_send(path,receipt)
    with connect(path) as conn:
        acknowledge(conn,receipt,'OUTCOME_UNKNOWN')
        for operator,reason in [(None,'reason'),('','reason'),('person',None),('person','')]:
            with pytest.raises(InvalidTransition):
                resolve(conn,receipt,'REJECTED',evidence_sha256=PROOF,operator_id=operator,reason=reason)
        assert conn.execute('SELECT state FROM provider_dispatch_receipts').fetchone()[0]=='RECONCILIATION_PENDING'
