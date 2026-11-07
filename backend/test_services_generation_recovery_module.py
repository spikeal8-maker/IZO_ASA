from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from app.database.connection import open_sqlite
from app.services.generation_recovery import (
    ACTIVE_GENERATION_STATUSES,
    RESUMABLE_VIDEO_PROVIDERS,
    STARTUP_INTERRUPTION_MESSAGE,
    reconcile_stale_generation_jobs,
)


NOW = "2026-07-14T00:45:00+00:00"


def connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            status TEXT NOT NULL,
            provider TEXT,
            progress INTEGER NOT NULL,
            result_image_id TEXT,
            error_message TEXT,
            completed_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE images (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            job_id TEXT,
            deleted_at TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    return conn


def insert_job(
    conn: sqlite3.Connection,
    job_id: str,
    status: str,
    provider: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO jobs (id, user_id, status, provider, progress, created_at) "
        "VALUES (?, 'user-1', ?, ?, 24, ?)",
        (job_id, status, provider, NOW),
    )


def test_active_status_contract_is_explicit_and_stable() -> None:
    assert ACTIVE_GENERATION_STATUSES == (
        "queued",
        "running",
        "uploading",
        "sent_to_comfyui",
        "sent_to_openrouter",
    )
    assert STARTUP_INTERRUPTION_MESSAGE == "Генерация прервана перезапуском сервиса. Токены возвращены."
    assert RESUMABLE_VIDEO_PROVIDERS == ("openrouter", "local_ltx")


def test_resumable_video_jobs_survive_startup_reconciliation() -> None:
    conn = connection()
    for provider in RESUMABLE_VIDEO_PROVIDERS:
        insert_job(conn, f"video-{provider}", "queued", provider)

    report = reconcile_stale_generation_jobs(
        conn,
        completed_at=NOW,
        refund_job=lambda *_args: pytest.fail("resumable video must not refund"),
    )

    assert report.checked == 0
    statuses = conn.execute("SELECT status FROM jobs ORDER BY id").fetchall()
    assert [row["status"] for row in statuses] == ["queued", "queued"]


def test_all_orphaned_active_states_fail_and_request_refund() -> None:
    conn = connection()
    for index, status in enumerate(ACTIVE_GENERATION_STATUSES):
        insert_job(conn, f"job-{index}", status)
    refunded: list[tuple[str, str]] = []

    report = reconcile_stale_generation_jobs(
        conn,
        completed_at=NOW,
        refund_job=lambda _conn, job_id, reason: refunded.append((job_id, reason)) or True,
    )

    assert report.as_dict() == {"checked": 5, "completed_from_images": 0, "failed": 5, "refunds_created": 5}
    assert refunded == [(f"job-{index}", "startup_reconciliation") for index in range(5)]
    rows = conn.execute(
        "SELECT status, progress, result_image_id, error_message, completed_at FROM jobs ORDER BY id"
    ).fetchall()
    assert all(dict(row) == {
        "status": "failed",
        "progress": 100,
        "result_image_id": None,
        "error_message": STARTUP_INTERRUPTION_MESSAGE,
        "completed_at": NOW,
    } for row in rows)


def test_saved_active_image_completes_job_without_refund() -> None:
    conn = connection()
    insert_job(conn, "job-image", "sent_to_comfyui")
    conn.execute(
        "INSERT INTO images (id, user_id, job_id, deleted_at, created_at) VALUES "
        "('image-1', 'user-1', 'job-image', NULL, '2026-07-14T00:44:00+00:00')"
    )

    report = reconcile_stale_generation_jobs(
        conn,
        completed_at=NOW,
        refund_job=lambda *_args: pytest.fail("completed recovery must not refund"),
    )

    assert report.as_dict() == {"checked": 1, "completed_from_images": 1, "failed": 0, "refunds_created": 0}
    row = conn.execute(
        "SELECT status, progress, result_image_id, error_message, completed_at FROM jobs WHERE id='job-image'"
    ).fetchone()
    assert dict(row) == {
        "status": "completed",
        "progress": 100,
        "result_image_id": "image-1",
        "error_message": None,
        "completed_at": "2026-07-14T00:44:00+00:00",
    }


def test_deleted_image_is_not_treated_as_success() -> None:
    conn = connection()
    insert_job(conn, "job-deleted", "running")
    conn.execute(
        "INSERT INTO images (id, user_id, job_id, deleted_at, created_at) VALUES "
        "('image-deleted', 'user-1', 'job-deleted', '2026-07-14T00:44:30+00:00', '2026-07-14T00:44:00+00:00')"
    )

    report = reconcile_stale_generation_jobs(
        conn,
        completed_at=NOW,
        refund_job=lambda *_args, **_kwargs: True,
    )

    assert report.failed == 1 and report.completed_from_images == 0
    assert conn.execute("SELECT status FROM jobs WHERE id='job-deleted'").fetchone()[0] == "failed"


def test_terminal_jobs_are_untouched_and_second_run_is_noop() -> None:
    conn = connection()
    for status in ("completed", "failed", "cancelled"):
        insert_job(conn, f"terminal-{status}", status)
    insert_job(conn, "active", "queued")
    refunds: list[str] = []

    first = reconcile_stale_generation_jobs(
        conn,
        completed_at=NOW,
        refund_job=lambda _conn, job_id, reason: refunds.append(job_id) or True,
    )
    second = reconcile_stale_generation_jobs(
        conn,
        completed_at=NOW,
        refund_job=lambda *_args: pytest.fail("second run must not refund"),
    )

    assert first.checked == 1 and refunds == ["active"]
    assert second.as_dict() == {"checked": 0, "completed_from_images": 0, "failed": 0, "refunds_created": 0}
    terminal = conn.execute("SELECT id, status, progress FROM jobs WHERE id LIKE 'terminal-%' ORDER BY id").fetchall()
    assert [(row["id"], row["status"], row["progress"]) for row in terminal] == [
        ("terminal-cancelled", "cancelled", 24),
        ("terminal-completed", "completed", 24),
        ("terminal-failed", "failed", 24),
    ]


def test_refund_exception_keeps_job_active_for_transaction_rollback() -> None:
    conn = connection()
    insert_job(conn, "job-error", "uploading")
    conn.commit()

    with pytest.raises(RuntimeError, match="ledger unavailable"):
        with conn:
            reconcile_stale_generation_jobs(
                conn,
                completed_at=NOW,
                refund_job=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ledger unavailable")),
            )

    row = conn.execute("SELECT status, progress, completed_at FROM jobs WHERE id='job-error'").fetchone()
    assert dict(row) == {"status": "uploading", "progress": 24, "completed_at": None}


@pytest.fixture
def persisted_recovery_connections(tmp_path):
    path = tmp_path / "recovery.sqlite"
    with closing(connection()) as template, closing(open_sqlite(path, busy_timeout_ms=30)) as first:
        template.backup(first)
        with closing(open_sqlite(path, busy_timeout_ms=30)) as second:
            assert first.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            yield first, second


@pytest.mark.parametrize("mode", ("fresh", "autocommit", "deferred", "read", "write", "savepoint"))
@pytest.mark.parametrize("commit", (False, True))
def test_writer_reserved_before_reads_until_caller_finishes(persisted_recovery_connections, mode, commit):
    first, second = persisted_recovery_connections
    first.executescript(
        "CREATE TABLE caller_work (value TEXT); CREATE TABLE recovery_updates (job_id TEXT); "
        "CREATE TRIGGER observe_job_update AFTER UPDATE ON jobs BEGIN "
        "INSERT INTO recovery_updates VALUES (new.id); END;"
    )
    insert_job(first, "reserved", "queued")
    first.commit()
    if mode == "autocommit":
        first.isolation_level = None
    elif mode != "fresh":
        first.execute("BEGIN")
    if mode == "read":
        first.execute("SELECT * FROM jobs").fetchall()
    if mode in ("write", "savepoint"):
        first.execute("INSERT INTO caller_work VALUES ('owned')")
    if mode == "savepoint":
        first.execute("SAVEPOINT caller_owned")
    changes_before = first.total_changes
    reservations = []

    def trace(statement):
        if statement.lstrip().startswith("SELECT id, user_id"):
            try:
                second.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as error:
                reservations.append(error.sqlite_errorcode)
            else:
                second.rollback()
                reservations.append(None)

    def refund(conn, _job_id, *, reason):
        assert conn is first and conn.in_transaction and reason == "startup_reconciliation"
        assert conn.total_changes == changes_before
        assert conn.execute("SELECT COUNT(*) FROM recovery_updates").fetchone()[0] == 0
        return False

    first.set_trace_callback(trace)
    report = reconcile_stale_generation_jobs(first, completed_at=NOW, refund_job=refund)
    first.set_trace_callback(None)
    assert reservations == [sqlite3.SQLITE_BUSY]
    assert report.failed == 1 and first.in_transaction
    assert second.execute("SELECT status FROM jobs").fetchone()[0] == "queued"
    assert second.execute("SELECT COUNT(*) FROM caller_work").fetchone()[0] == 0
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        second.execute("BEGIN IMMEDIATE")
    if mode == "savepoint":
        first.execute("ROLLBACK TO caller_owned")
        assert first.execute("SELECT status FROM jobs").fetchone()[0] == "queued"
        assert first.execute("SELECT COUNT(*) FROM caller_work").fetchone()[0] == 1
        first.execute("RELEASE caller_owned")
    if commit:
        first.commit()
    else:
        first.rollback()
    assert not first.in_transaction
    expected_status = "failed" if commit and mode != "savepoint" else "queued"
    assert second.execute("SELECT status FROM jobs").fetchone()[0] == expected_status
    assert second.execute("SELECT COUNT(*) FROM caller_work").fetchone()[0] == int(
        commit and mode in ("write", "savepoint")
    )
    second.execute("BEGIN IMMEDIATE")
    second.rollback()


@pytest.mark.parametrize("state", ("fresh", "deferred", "read", "stale"))
def test_reservation_conflict_precedes_reads_and_refunds(persisted_recovery_connections, state):
    first, second = persisted_recovery_connections
    insert_job(first, "conflict", "running")
    first.commit()
    if state != "fresh":
        first.execute("BEGIN")
    if state in ("read", "stale"):
        first.execute("SELECT * FROM jobs").fetchall()
    second.execute("BEGIN IMMEDIATE")
    second.execute("UPDATE jobs SET progress=31")
    if state == "stale":
        second.commit()
    statements = []
    first.set_trace_callback(statements.append)
    changes_before = first.total_changes
    with pytest.raises(sqlite3.OperationalError) as captured:
        reconcile_stale_generation_jobs(
            first, completed_at=NOW,
            refund_job=lambda *_args, **_kwargs: pytest.fail("reservation failed before refund"),
        )
    first.set_trace_callback(None)
    expected_code = sqlite3.SQLITE_BUSY_SNAPSHOT if state == "stale" else sqlite3.SQLITE_BUSY
    assert captured.value.sqlite_errorcode == expected_code
    assert not any(statement.lstrip().startswith("SELECT") for statement in statements)
    assert first.total_changes == changes_before
    assert first.in_transaction is (state != "fresh")
    if state in ("read", "stale"):
        assert first.execute("SELECT progress FROM jobs").fetchone()[0] == 24
    first.rollback()
    second.rollback()
    assert first.execute("SELECT progress FROM jobs").fetchone()[0] == (31 if state == "stale" else 24)


def test_refund_exception_preserves_caller_transaction_until_rollback(persisted_recovery_connections):
    first, second = persisted_recovery_connections
    first.execute("CREATE TABLE caller_work (value TEXT)")
    insert_job(first, "rollback", "uploading")
    first.commit()
    first.execute("INSERT INTO caller_work VALUES ('prior')")

    def failing_refund(conn, _job_id, *, reason):
        assert reason == "startup_reconciliation"
        conn.execute("INSERT INTO caller_work VALUES ('refund-side-effect')")
        raise RuntimeError("refund interrupted")

    with pytest.raises(RuntimeError, match="refund interrupted"):
        reconcile_stale_generation_jobs(first, completed_at=NOW, refund_job=failing_refund)
    assert first.in_transaction
    assert first.execute("SELECT COUNT(*) FROM caller_work").fetchone()[0] == 2
    assert second.execute("SELECT COUNT(*) FROM caller_work").fetchone()[0] == 0
    assert first.execute("SELECT status FROM jobs").fetchone()[0] == "uploading"
    first.rollback()
    assert not first.in_transaction
    assert first.execute("SELECT COUNT(*) FROM caller_work").fetchone()[0] == 0
