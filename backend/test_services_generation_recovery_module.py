from __future__ import annotations

import sqlite3

import pytest

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
