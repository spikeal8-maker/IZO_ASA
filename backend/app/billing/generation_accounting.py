"""Charge generation operations and durably serialize accounting reversals."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any


def refund_generation_tokens(conn: sqlite3.Connection, job_id: str, *, reason: str) -> bool:
    """Caller commits; a failed reversal never leaves a partial balance change."""
    if conn.in_transaction:
        conn.execute("UPDATE generation_refunds SET job_id = job_id WHERE 0")
    else:
        conn.execute("BEGIN IMMEDIATE")
    if conn.execute("SELECT 1 FROM generation_refunds WHERE job_id = ?", (job_id,)).fetchone():
        return False
    savepoint = "generation_refund_" + uuid.uuid4().hex
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        ledger_id = _apply_generation_refund(conn, job_id, reason=reason)
        if ledger_id is not None:
            conn.execute(
                "INSERT INTO generation_refunds (job_id, ledger_id, created_at) VALUES (?, ?, ?)",
                (job_id, ledger_id, datetime.now(timezone.utc).isoformat()),
            )
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        return ledger_id is not None
    except BaseException:
        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise


def _apply_generation_refund(conn: sqlite3.Connection, job_id: str, *, reason: str) -> str | None:
    """Idempotently reverse a generation charge for failed/cancelled jobs."""
    existing_refund = conn.execute(
        "SELECT 1 FROM token_ledger WHERE reason IN ('generation_refund', 'daily_generation_refund', 'openrouter_monthly_generation_refund') AND CASE WHEN json_valid(meta_json) THEN json_extract(meta_json, '$.jobId') END = ?",
        (job_id,),
    ).fetchone()
    if existing_refund is not None:
        return None
    charge = conn.execute(
        """
        SELECT * FROM token_ledger
        WHERE reason IN ('generation', 'daily_generation', 'openrouter_monthly_generation') AND CASE WHEN json_valid(meta_json) THEN json_extract(meta_json, '$.jobId') END = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (job_id,),
    ).fetchone()
    if charge is None:
        return None
    meta = json.loads(charge["meta_json"])
    user_id = charge["user_id"]
    token_cost = int(meta.get("token_cost") or abs(int(charge["delta"] or 0)) or 0)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    today = now.strftime("%Y-%m-%d")
    month_key = now.strftime("%Y-%m")
    if "daily_part" in meta or "balance_part" in meta:
        daily_part = max(0, int(meta.get("daily_part") or 0))
        balance_part = max(0, int(meta.get("balance_part") or 0))
        user_row = conn.execute(
            "SELECT daily_tokens_used, last_daily_reset FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if user_row is not None and user_row["last_daily_reset"] == today and daily_part > 0:
            conn.execute(
                "UPDATE users SET daily_tokens_used = MAX(0, daily_tokens_used - ?) WHERE id = ?",
                (daily_part, user_id),
            )
        if balance_part > 0:
            conn.execute(
                "UPDATE users SET token_balance = token_balance + ? WHERE id = ?",
                (balance_part, user_id),
            )
        refund_delta = balance_part
        refund_reason = "generation_refund" if balance_part > 0 else "daily_generation_refund"
    elif charge["reason"] == "daily_generation":
        user_row = conn.execute("SELECT daily_tokens_used, last_daily_reset FROM users WHERE id = ?", (user_id,)).fetchone()
        if user_row is not None and user_row["last_daily_reset"] == today and token_cost > 0:
            new_daily = max(0, int(user_row["daily_tokens_used"] or 0) - token_cost)
            conn.execute("UPDATE users SET daily_tokens_used = ? WHERE id = ?", (new_daily, user_id))
        refund_delta = 0
        refund_reason = "daily_generation_refund"
    elif charge["reason"] == "openrouter_monthly_generation":
        monthly_part = max(0, int(meta.get("openrouter_monthly_used_after") or 0) - int(meta.get("openrouter_monthly_used_before") or 0))
        user_row = conn.execute("SELECT openrouter_monthly_tokens_used, last_openrouter_month_reset FROM users WHERE id = ?", (user_id,)).fetchone()
        if user_row is not None and user_row["last_openrouter_month_reset"] == month_key and monthly_part > 0:
            new_monthly = max(0, int(user_row["openrouter_monthly_tokens_used"] or 0) - monthly_part)
            conn.execute("UPDATE users SET openrouter_monthly_tokens_used = ? WHERE id = ?", (new_monthly, user_id))
        refund_delta = abs(int(charge["delta"] or 0))
        refund_reason = "openrouter_monthly_generation_refund"
        if refund_delta > 0:
            conn.execute("UPDATE users SET token_balance = token_balance + ? WHERE id = ?", (refund_delta, user_id))
    else:
        refund_delta = abs(int(charge["delta"] or 0))
        refund_reason = "generation_refund"
        if refund_delta > 0:
            conn.execute("UPDATE users SET token_balance = token_balance + ? WHERE id = ?", (refund_delta, user_id))
    if token_cost > 0:
        conn.execute(
            """
            UPDATE users
            SET tokens_used = MAX(0, tokens_used - ?),
                generation_count = MAX(0, generation_count - 1)
            WHERE id = ?
            """,
            (token_cost, user_id),
        )
    refund_ledger_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO token_ledger (id, user_id, delta, reason, meta_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            refund_ledger_id,
            user_id,
            refund_delta,
            refund_reason,
            json.dumps(
                {
                    "jobId": job_id,
                    "reason": reason,
                    "refunded_ledger_id": charge["id"],
                    "token_cost": token_cost,
                    "daily_part": max(0, int(meta.get("daily_part") or 0)),
                    "balance_part": refund_delta,
                },
                ensure_ascii=False,
            ),
            now_iso,
        ),
    )
    return refund_ledger_id



def charge_generation_tokens(conn: sqlite3.Connection, user_id: str, token_cost: int, job_id: str, req: Any, billing_snapshot: dict[str, Any] | None = None, *, reconcile_tariff: Callable, tariff_config: Callable, error: Callable[[int, str], Exception]) -> dict[str, Any]:
    """Reserve tokens for a generation after request validation has passed.

    There are exactly two accounts: the daily tariff allowance and the main
    balance. Local server generations consume daily tokens first and then the
    main balance. API generations consume the main balance only.
    """
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    today = now.strftime("%Y-%m-%d")
    user_row = conn.execute(
        "SELECT id, internal_user_id, token_balance, plan, daily_tokens_used, last_daily_reset FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if user_row is None:
        raise error(404, "User not found.")
    if user_row["internal_user_id"]:
        reconcile_tariff(conn, str(user_row["internal_user_id"]), now=now)
        user_row = conn.execute(
            "SELECT id, internal_user_id, token_balance, plan, daily_tokens_used, last_daily_reset FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

    old_balance = int(user_row["token_balance"] or 0)
    daily_limit = 0
    daily_used_before = int(user_row["daily_tokens_used"] or 0)
    if user_row["last_daily_reset"] != today:
        daily_used_before = 0
    daily_part = 0
    balance_part = 0

    if user_id != "demo_user":
        tariff = tariff_config(conn)[str(user_row["plan"] or "mini").lower()]
        daily_limit = int(tariff["daily_tokens"])
        if req.provider != "openrouter":
            daily_part = min(token_cost, max(0, daily_limit - daily_used_before))
        balance_part = max(0, token_cost - daily_part)
        if old_balance < balance_part:
            raise error(402, "Not enough tokens.")

    daily_used_after = daily_used_before + daily_part
    new_balance = old_balance - balance_part if user_id != "demo_user" else old_balance
    ledger_reason = "daily_generation" if daily_part > 0 and balance_part == 0 else "generation"
    conn.execute(
        """
        UPDATE users
        SET token_balance = ?,
            daily_tokens_used = ?,
            last_daily_reset = ?,
            tokens_used = tokens_used + ?,
            generation_count = generation_count + 1,
            last_seen_at = ?
        WHERE id = ?
        """,
        (new_balance, daily_used_after, today, token_cost, now_iso, user_id),
    )
    conn.execute(
        "INSERT INTO token_ledger (id, user_id, delta, reason, meta_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()),
            user_id,
            -balance_part,
            ledger_reason,
            json.dumps(
                {
                    "jobId": job_id,
                    "mode": req.mode,
                    "provider": req.provider,
                    "token_cost": token_cost,
                    "billing": billing_snapshot or None,
                    "used_daily_budget": daily_part > 0,
                    "daily_part": daily_part,
                    "balance_part": balance_part,
                    "daily_tokens_used_before": daily_used_before,
                    "daily_tokens_used_after": daily_used_after,
                    "daily_tokens_limit": daily_limit,
                    "balance_delta": -balance_part,
                },
                ensure_ascii=False,
            ),
            now_iso,
        ),
    )
    return {
        "used_daily": daily_part > 0,
        "old_balance": old_balance,
        "new_balance": new_balance,
        "balance_delta": -balance_part,
        "daily_part": daily_part,
        "balance_part": balance_part,
        "daily_tokens_used": daily_used_after,
        "daily_tokens_limit": daily_limit,
        "daily_tokens_remaining": max(0, daily_limit - daily_used_after),
    }
