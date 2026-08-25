"""Bounded image trial for email/password accounts awaiting social proof."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


TRIAL_GENERATION_LIMIT = 5
TRIAL_REMINDER_SECONDS = 2 * 60 * 60
TRIAL_ACCESS_SECONDS = 24 * 60 * 60
TRIAL_MODEL_PROFILE = "local_flux_klein"


class TrialAccessDenied(RuntimeError):
    def __init__(self, detail: dict[str, Any]):
        super().__init__(str(detail.get("message") or "trial_access_denied"))
        self.detail = detail


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _counts(conn: sqlite3.Connection, internal_user_id: str) -> tuple[int, int]:
    row = conn.execute(
        """
        SELECT
          COALESCE(SUM(CASE WHEN state='consumed' THEN 1 ELSE 0 END), 0) AS consumed,
          COALESCE(SUM(CASE WHEN state='reserved' THEN 1 ELSE 0 END), 0) AS reserved
        FROM generation_trial_reservations WHERE internal_user_id=?
        """,
        (internal_user_id,),
    ).fetchone()
    return int(row["consumed"]), int(row["reserved"])


def trial_payload(
    conn: sqlite3.Connection,
    internal_user_id: str,
    *,
    required_at: str,
    pending: bool,
    now: str,
) -> dict[str, Any]:
    consumed, reserved = _counts(conn, internal_user_id)
    used = consumed + reserved
    required = _utc(required_at)
    now_dt = _utc(now)
    expires_at = (required + timedelta(seconds=TRIAL_ACCESS_SECONDS)).isoformat()
    reminder_at = (required + timedelta(seconds=TRIAL_REMINDER_SECONDS)).isoformat()
    blocked = pending and (used >= TRIAL_GENERATION_LIMIT or now_dt >= _utc(expires_at))
    return {
        "trial_generation_limit": TRIAL_GENERATION_LIMIT,
        "trial_generations_consumed": consumed,
        "trial_generations_reserved": reserved,
        "trial_generations_remaining": max(0, TRIAL_GENERATION_LIMIT - used),
        "trial_reminder_at": reminder_at,
        "trial_expires_at": expires_at,
        "trial_reminder_due": pending and now_dt >= _utc(reminder_at),
        "trial_generation_blocked": blocked,
    }


def gate_detail(
    conn: sqlite3.Connection,
    internal_user_id: str,
    *,
    now: str,
    mode: str,
    provider: str,
    model_profile: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT status, required_at FROM account_verifications WHERE internal_user_id=?",
        (internal_user_id,),
    ).fetchone()
    if row is None or row["status"] != "pending":
        return None
    state = trial_payload(
        conn, internal_user_id, required_at=row["required_at"], pending=True, now=now,
    )
    if mode != "text_to_image" or provider != "comfyui" or model_profile != TRIAL_MODEL_PROFILE:
        return {
            "code": "social_verification_required",
            "message": "До подтверждения доступны только пробные генерации базовой модели.",
            **state,
        }
    if state["trial_generation_blocked"]:
        return {
            "code": "social_verification_required",
            "message": "Пробный доступ завершён. Подтвердите аккаунт через MAX или Telegram.",
            **state,
        }
    return None


def reserve_trial_generation(
    conn: sqlite3.Connection,
    internal_user_id: str,
    job_id: str,
    *,
    now: str,
) -> dict[str, Any] | None:
    # Serialize the count-and-insert decision across SQLite connections. The
    # request commits or rolls back this reservation together with its job.
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    row = conn.execute(
        "SELECT status, required_at FROM account_verifications WHERE internal_user_id=?",
        (internal_user_id,),
    ).fetchone()
    if row is None or row["status"] != "pending":
        return None
    state = trial_payload(
        conn, internal_user_id, required_at=row["required_at"], pending=True, now=now,
    )
    if state["trial_generation_blocked"]:
        raise TrialAccessDenied({
            "code": "social_verification_required",
            "message": "Пробный доступ завершён. Подтвердите аккаунт через MAX или Telegram.",
            **state,
        })
    conn.execute(
        """
        INSERT INTO generation_trial_reservations
          (job_id, internal_user_id, source, state, reserved_at, settled_at)
        VALUES (?, ?, 'registered', 'reserved', ?, NULL)
        """,
        (job_id, internal_user_id, now),
    )
    return trial_payload(
        conn, internal_user_id, required_at=row["required_at"], pending=True, now=now,
    )


def reserve_or_charge_generation(
    conn: sqlite3.Connection,
    internal_user_id: str,
    job_id: str,
    *,
    now: str,
    charge: Callable[[], dict[str, Any]],
    job: dict[str, Any],
    denied: Callable[[dict[str, Any]], Exception],
) -> dict[str, Any]:
    """Atomically reserve a pending-account attempt or apply normal billing."""
    try:
        trial = reserve_trial_generation(conn, internal_user_id, job_id, now=now)
    except TrialAccessDenied as exc:
        raise denied(exc.detail) from exc
    if trial is None:
        return charge()
    job.update(tokenCost=0, trialAccess=trial)
    return {
        "used_daily": False, "new_balance": 0, "daily_part": 0,
        "balance_part": 0, "daily_tokens_used": 0,
        "daily_tokens_limit": 0, "daily_tokens_remaining": 0,
    }


def settle_trial_generation(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    job_status: str,
    now: str,
) -> bool:
    target = "consumed" if job_status == "completed" else "released" if job_status in {"failed", "cancelled"} else None
    if target is None:
        return False
    return bool(conn.execute(
        """
        UPDATE generation_trial_reservations SET state=?, settled_at=?
        WHERE job_id=? AND state='reserved'
        """,
        (target, now, job_id),
    ).rowcount)
