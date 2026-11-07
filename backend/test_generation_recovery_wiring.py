from __future__ import annotations

import inspect
import json
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from types import SimpleNamespace

import pytest

import main


@pytest.mark.parametrize("contenders", (1, 2, 5, 10))
@pytest.mark.parametrize("refund_fails", (False, True))
def test_main_reconciliation_uses_existing_idempotent_refund(monkeypatch, contenders, refund_fails) -> None:
    job_id = "job-startup-recovery"
    user_id = "web-startup-recovery"
    original_db = main.db
    connections = []
    closed_connections = []

    @contextmanager
    def owned_db():
        connection = original_db()
        connections.append(connection)
        try:
            with closing(connection):
                with connection:
                    yield connection
        finally:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                connection.execute("SELECT 1")
            closed_connections.append(id(connection))

    monkeypatch.setattr(main, "db", owned_db)
    main.init_db()
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, language, role, token_balance, tokens_used, generation_count, created_at, last_login_at) "
            "VALUES (?, 'ru', 'user', 97, 3, 1, '2026-07-14T00:40:00+00:00', '2026-07-14T00:40:00+00:00')",
            (user_id,),
        )
        conn.execute(
            "INSERT INTO jobs (id, user_id, mode, provider, status, progress, prompt_original, settings_json, created_at) "
            "VALUES (?, ?, 'text_to_image', 'comfyui', 'sent_to_comfyui', 24, '', '{}', '2026-07-14T00:40:00+00:00')",
            (job_id, user_id),
        )
        conn.execute(
            "INSERT INTO token_ledger (id, user_id, delta, reason, meta_json, created_at) VALUES (?, ?, -3, 'generation', ?, ?)",
            (
                str(uuid.uuid4()),
                user_id,
                json.dumps({"jobId": job_id, "token_cost": 3}, ensure_ascii=False),
                "2026-07-14T00:40:00+00:00",
            ),
        )

    start = threading.Barrier(contenders, timeout=10)
    absent_reads = threading.Barrier(contenders, timeout=10)
    read_transactions = []
    original_refund = main.refund_generation_tokens

    def observed_refund(conn, current_job, *, reason):
        class RefundConnection:
            def execute(self, sql, parameters=()):
                cursor = conn.execute(sql, parameters)
                if sql.startswith("SELECT 1 FROM token_ledger WHERE reason IN "):
                    row = cursor.fetchone()
                    read_transactions.append(conn.in_transaction)
                    if not conn.in_transaction:
                        absent_reads.wait()
                    return SimpleNamespace(fetchone=lambda: row)
                return cursor

        refunded = original_refund(RefundConnection(), current_job, reason=reason)
        if refund_fails:
            raise RuntimeError("synthetic failure after refund")
        return refunded

    def recover(_index):
        start.wait()
        if refund_fails:
            with pytest.raises(RuntimeError, match="synthetic failure after refund"):
                main.reconcile_stale_generation_state()
            return None
        return main.reconcile_stale_generation_state()

    monkeypatch.setattr(main, "refund_generation_tokens", observed_refund)
    with ThreadPoolExecutor(max_workers=contenders) as executor:
        reports = list(executor.map(recover, range(contenders)))
    assert read_transactions == [True] * (contenders if refund_fails else 1)
    if refund_fails:
        with main.db() as conn:
            assert conn.execute("SELECT COUNT(*) FROM token_ledger WHERE user_id=?", (user_id,)).fetchone()[0] == 1
            assert tuple(conn.execute(
                "SELECT token_balance, tokens_used, generation_count FROM users WHERE id=?", (user_id,)
            ).fetchone()) == (97, 3, 1)
            assert conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()[0] == "sent_to_comfyui"
        monkeypatch.setattr(main, "refund_generation_tokens", original_refund)
        report = main.reconcile_stale_generation_state()
    else:
        report = {key: sum(result[key] for result in reports) for key in reports[0]}

    assert report == {"checked": 1, "completed_from_images": 0, "failed": 1, "refunds_created": 1}
    with main.db() as conn:
        job = conn.execute(
            "SELECT status, progress, error_message, completed_at FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone()
        user = conn.execute(
            "SELECT token_balance, tokens_used, generation_count FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
        refund = conn.execute(
            "SELECT reason, delta, meta_json FROM token_ledger WHERE reason='generation_refund'"
        ).fetchone()
        assert conn.execute(
            "SELECT COUNT(*) FROM token_ledger WHERE reason='generation_refund' AND user_id=?", (user_id,)
        ).fetchone()[0] == 1
    assert job["status"] == "failed" and job["progress"] == 100 and job["completed_at"]
    assert job["error_message"] == main.generation_recovery.STARTUP_INTERRUPTION_MESSAGE
    assert dict(user) == {"token_balance": 100, "tokens_used": 0, "generation_count": 0}
    assert refund["delta"] == 3 and json.loads(refund["meta_json"])["reason"] == "startup_reconciliation"
    assert sorted(closed_connections) == sorted(id(connection) for connection in connections)


def test_startup_reconciles_before_loading_in_memory_jobs() -> None:
    source = inspect.getsource(main.startup)

    assert source.index("reconcile_stale_generation_state()") < source.index("load_db_state()")
