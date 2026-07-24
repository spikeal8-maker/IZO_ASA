"""Transactional startup recovery for generation jobs orphaned by a restart."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


ACTIVE_GENERATION_STATUSES = (
    "queued",
    "running",
    "uploading",
    "sent_to_comfyui",
    "sent_to_openrouter",
)
RESUMABLE_VIDEO_PROVIDERS = ("openrouter", "local_ltx")
STARTUP_INTERRUPTION_MESSAGE = "Генерация прервана перезапуском сервиса. Токены возвращены."


class RecoveryConnection(Protocol):
    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> Any: ...


class RefundJob(Protocol):
    def __call__(
        self,
        conn: RecoveryConnection,
        job_id: str,
        *,
        reason: str,
    ) -> bool: ...


@dataclass(frozen=True)
class GenerationRecoveryReport:
    checked: int = 0
    completed_from_images: int = 0
    failed: int = 0
    refunds_created: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "checked": self.checked,
            "completed_from_images": self.completed_from_images,
            "failed": self.failed,
            "refunds_created": self.refunds_created,
        }


def reconcile_stale_generation_jobs(
    conn: RecoveryConnection,
    *,
    completed_at: str,
    refund_job: RefundJob,
) -> GenerationRecoveryReport:
    """Finish jobs that cannot be resumed by the new single-process worker.

    A persisted active image proves that generation output was already committed,
    so that job is completed without a refund. Every other active row belongs to
    the previous process, is failed, and uses the existing idempotent refund path.
    The caller owns the transaction; exceptions intentionally roll it back.
    """

    placeholders = ",".join("?" for _ in ACTIVE_GENERATION_STATUSES)
    rows = conn.execute(
        f"""
        SELECT id, user_id
        FROM jobs
        WHERE status IN ({placeholders})
          AND COALESCE(provider, '') NOT IN (?, ?)
        ORDER BY created_at, id
        """,
        (*ACTIVE_GENERATION_STATUSES, *RESUMABLE_VIDEO_PROVIDERS),
    ).fetchall()
    completed_from_images = 0
    failed = 0
    refunds_created = 0

    for row in rows:
        job_id = str(row["id"])
        user_id = str(row["user_id"] or "")
        image = conn.execute(
            """
            SELECT id, created_at
            FROM images
            WHERE job_id = ? AND user_id = ? AND deleted_at IS NULL
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (job_id, user_id),
        ).fetchone()
        if image is not None:
            conn.execute(
                f"""
                UPDATE jobs
                SET status = 'completed', progress = 100, result_image_id = ?,
                    error_message = NULL, completed_at = ?
                WHERE id = ? AND status IN ({placeholders})
                """,
                (str(image["id"]), str(image["created_at"] or completed_at), job_id, *ACTIVE_GENERATION_STATUSES),
            )
            completed_from_images += 1
            continue

        if refund_job(conn, job_id, reason="startup_reconciliation"):
            refunds_created += 1
        conn.execute(
            f"""
            UPDATE jobs
            SET status = 'failed', progress = 100, result_image_id = NULL,
                error_message = ?, completed_at = ?
            WHERE id = ? AND status IN ({placeholders})
            """,
            (STARTUP_INTERRUPTION_MESSAGE, completed_at, job_id, *ACTIVE_GENERATION_STATUSES),
        )
        failed += 1

    return GenerationRecoveryReport(
        checked=len(rows),
        completed_from_images=completed_from_images,
        failed=failed,
        refunds_created=refunds_created,
    )
