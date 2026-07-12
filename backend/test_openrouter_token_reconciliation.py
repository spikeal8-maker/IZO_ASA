import json
import sqlite3

from backend.main import reconcile_openrouter_token_charge


def connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, token_balance INTEGER, openrouter_monthly_tokens_used INTEGER, tokens_used INTEGER)")
    conn.execute("CREATE TABLE token_ledger (id TEXT, user_id TEXT, delta INTEGER, reason TEXT, meta_json TEXT, created_at TEXT)")
    conn.execute("INSERT INTO users VALUES ('u1', 90, 50, 10)")
    return conn


def add_charge(conn: sqlite3.Connection, *, balance_delta: int, monthly: int, charged: int) -> None:
    conn.execute(
        "INSERT INTO token_ledger VALUES ('charge', 'u1', ?, 'openrouter_monthly_generation', ?, 'now')",
        (-balance_delta, json.dumps({"jobId": "job-1", "token_cost": charged, "openrouter_monthly_used_before": 50 - monthly, "openrouter_monthly_used_after": 50})),
    )


def test_reconciliation_refunds_balance_before_monthly_package() -> None:
    conn = connection()
    add_charge(conn, balance_delta=4, monthly=6, charged=10)
    result = reconcile_openrouter_token_charge(conn, "job-1", 3)
    user = conn.execute("SELECT * FROM users WHERE id='u1'").fetchone()
    assert result == {"adjusted": True, "refund": 7, "actual": 3, "settled": 3}
    assert user["token_balance"] == 94
    assert user["openrouter_monthly_tokens_used"] == 47
    assert user["tokens_used"] == 3


def test_reconciliation_is_idempotent() -> None:
    conn = connection()
    add_charge(conn, balance_delta=2, monthly=3, charged=5)
    first = reconcile_openrouter_token_charge(conn, "job-1", 2)
    second = reconcile_openrouter_token_charge(conn, "job-1", 2)
    assert first["refund"] == 3
    assert second == {"adjusted": False, "refund": 3, "actual": 2, "settled": 2}
    assert conn.execute("SELECT COUNT(*) FROM token_ledger WHERE reason='openrouter_generation_adjustment'").fetchone()[0] == 1


def test_underestimate_is_recorded_without_surprise_post_charge() -> None:
    conn = connection()
    add_charge(conn, balance_delta=1, monthly=1, charged=2)
    result = reconcile_openrouter_token_charge(conn, "job-1", 4)
    adjustment = json.loads(conn.execute("SELECT meta_json FROM token_ledger WHERE reason='openrouter_generation_adjustment'").fetchone()[0])
    assert result == {"adjusted": True, "refund": 0, "actual": 4, "settled": 2}
    assert adjustment["underestimated_tokens"] == 2
    assert conn.execute("SELECT token_balance FROM users WHERE id='u1'").fetchone()[0] == 90
