"""Serialized, composable refunds for an existing generation charge.

The caller owns commit/rollback and connection lifetime. No provider work occurs
under the write lock and no ambiguous provider operation is retried here.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any


CHARGES = ("generation", "daily_generation", "openrouter_monthly_generation")
REFUNDS = ("generation_refund", "daily_generation_refund", "openrouter_monthly_generation_refund")
ADJUSTMENT = "openrouter_generation_adjustment"


def ensure_write_transaction(conn: sqlite3.Connection) -> None:
    """Acquire the writer before reads, without committing caller-owned work.

    An existing transaction cannot run BEGIN again. A no-op write upgrades it
    before accounting reads; an obsolete deferred snapshot fails closed with
    SQLite's normal busy error rather than issuing a second refund.
    """
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    else:
        conn.execute("UPDATE token_ledger SET id = id WHERE 0")


def _meta(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _entry(conn: sqlite3.Connection, job_id: str, reasons: tuple[str, ...]):
    placeholders = ",".join("?" for _ in reasons)
    # Verify the parsed identity as well: LIKE is only a narrowing operation.
    rows = conn.execute(
        f"SELECT * FROM token_ledger WHERE reason IN ({placeholders}) "
        "AND meta_json LIKE ? ORDER BY created_at DESC",
        (*reasons, f"%{job_id}%"),
    ).fetchall()
    return next((row for row in rows if _meta(row["meta_json"]).get("jobId") == job_id), None)


def _parts(charge, meta: dict[str, Any]) -> tuple[int, int, int]:
    balance = max(0, -int(charge["delta"] or 0))
    daily = max(0, int(meta.get("daily_part") or 0))
    monthly = 0
    if charge["reason"] == "daily_generation" and "daily_part" not in meta:
        daily = max(0, int(meta.get("token_cost") or 0))
    if charge["reason"] == "openrouter_monthly_generation":
        monthly = max(0, int(meta.get("openrouter_monthly_used_after") or 0)
                      - int(meta.get("openrouter_monthly_used_before") or 0))
    return balance, daily, monthly


def _period_matches(row, column: str, charge, now: datetime, fmt: str) -> bool:
    if column not in row.keys():  # Legacy callers can supply reduced rows.
        return True
    period = now.strftime(fmt)
    if row[column] != period:
        return False
    try:
        charged_at = datetime.fromisoformat(str(charge["created_at"]).replace("Z", "+00:00"))
    except ValueError:
        return True  # Preserve legacy rows without an ISO charging timestamp.
    return charged_at.strftime(fmt) == period


def _restore(conn, charge, *, balance: int, daily: int, monthly: int, now: datetime) -> None:
    user_id = charge["user_id"]
    if balance:
        conn.execute("UPDATE users SET token_balance = token_balance + ? WHERE id = ?", (balance, user_id))
    if daily or monthly:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if user is not None and daily and _period_matches(user, "last_daily_reset", charge, now, "%Y-%m-%d"):
            conn.execute("UPDATE users SET daily_tokens_used = MAX(0, daily_tokens_used - ?) WHERE id = ?", (daily, user_id))
        if user is not None and monthly and _period_matches(user, "last_openrouter_month_reset", charge, now, "%Y-%m"):
            conn.execute("UPDATE users SET openrouter_monthly_tokens_used = MAX(0, openrouter_monthly_tokens_used - ?) WHERE id = ?", (monthly, user_id))


def refund_generation_tokens(conn: sqlite3.Connection, job_id: str, *, reason: str) -> bool:
    """Refund only the part not already restored by a cost adjustment."""
    ensure_write_transaction(conn)
    if _entry(conn, job_id, REFUNDS) is not None:
        return False
    charge = _entry(conn, job_id, CHARGES)
    if charge is None:
        return False
    meta = _meta(charge["meta_json"])
    token_cost = max(0, int(meta.get("token_cost") or abs(int(charge["delta"] or 0))))
    balance, daily, monthly = _parts(charge, meta)
    original_balance = balance
    adjustment = _entry(conn, job_id, (ADJUSTMENT,))
    adjusted = _meta(adjustment["meta_json"]) if adjustment is not None else {}
    # Cash movement is proven by the ledger delta, not duplicated metadata.
    adjusted_balance = min(balance, max(0, int(adjustment["delta"] or 0))) if adjustment is not None else 0
    adjusted_daily = min(daily, max(0, int(adjusted.get("daily_refund") or 0)))
    adjusted_monthly = min(monthly, max(0, int(adjusted.get("monthly_refund") or 0)))
    balance -= adjusted_balance
    daily -= adjusted_daily
    monthly -= adjusted_monthly
    refund_tokens = max(0, token_cost - adjusted_balance - adjusted_daily - adjusted_monthly)
    now = datetime.now(timezone.utc)
    _restore(conn, charge, balance=balance, daily=daily, monthly=monthly, now=now)
    if token_cost:
        conn.execute(
            "UPDATE users SET tokens_used = MAX(0, tokens_used - ?), "
            "generation_count = MAX(0, generation_count - 1) WHERE id = ?",
            (refund_tokens, charge["user_id"]),
        )
    refund_reason = ("openrouter_monthly_generation_refund" if charge["reason"] == "openrouter_monthly_generation"
                     else "generation_refund" if original_balance else "daily_generation_refund")
    refund_meta = {"jobId": job_id, "reason": reason, "refunded_ledger_id": charge["id"],
                   "token_cost": token_cost, "refund_tokens": refund_tokens,
                   "daily_part": daily, "balance_part": balance, "monthly_part": monthly}
    conn.execute(
        "INSERT INTO token_ledger (id,user_id,delta,reason,meta_json,created_at) VALUES (?,?,?,?,?,?)",
        (str(uuid.uuid4()), charge["user_id"], balance, refund_reason,
         json.dumps(refund_meta, ensure_ascii=False), now.isoformat()),
    )
    return True


def reconcile_openrouter_token_charge(conn: sqlite3.Connection, job_id: str, actual_tokens: int) -> dict[str, int | bool]:
    """Return an overestimate once; a fully refunded job cannot refund again."""
    ensure_write_transaction(conn)
    actual = max(1, int(actual_tokens))
    if _entry(conn, job_id, REFUNDS) is not None:
        return {"adjusted": False, "refund": 0, "actual": actual, "settled": 0}
    existing = _entry(conn, job_id, (ADJUSTMENT,))
    if existing is not None:
        meta = _meta(existing["meta_json"])
        return {"adjusted": False, "refund": int(meta.get("refund_tokens") or 0),
                "actual": int(meta.get("actual_tokens") or actual),
                "settled": int(meta.get("settled_tokens") or 0)}
    charge = _entry(conn, job_id, CHARGES)
    if charge is None:
        return {"adjusted": False, "refund": 0, "actual": actual, "settled": actual}
    meta = _meta(charge["meta_json"])
    charged = max(0, int(meta.get("token_cost") or 0))
    refund = max(0, charged - actual)
    balance, daily, monthly = _parts(charge, meta)
    balance_refund = min(refund, balance)
    monthly_refund = min(max(0, refund - balance_refund), monthly)
    daily_refund = min(max(0, refund - balance_refund - monthly_refund), daily)
    now = datetime.now(timezone.utc)
    _restore(conn, charge, balance=balance_refund, daily=daily_refund, monthly=monthly_refund, now=now)
    if refund:
        conn.execute("UPDATE users SET tokens_used = MAX(0, tokens_used - ?) WHERE id = ?", (refund, charge["user_id"]))
    adjustment_meta = {
        "jobId": job_id, "charged_tokens": charged, "actual_tokens": actual,
        "settled_tokens": min(charged, actual), "refund_tokens": refund,
        "balance_refund": balance_refund, "monthly_refund": monthly_refund, "daily_refund": daily_refund,
        "underestimated_tokens": max(0, actual - charged), "charged_ledger_id": charge["id"],
    }
    conn.execute(
        "INSERT INTO token_ledger (id,user_id,delta,reason,meta_json,created_at) VALUES (?,?,?,?,?,?)",
        (str(uuid.uuid4()), charge["user_id"], balance_refund, ADJUSTMENT,
         json.dumps(adjustment_meta, ensure_ascii=False), now.isoformat()),
    )
    return {"adjusted": True, "refund": refund, "actual": actual, "settled": min(charged, actual)}
