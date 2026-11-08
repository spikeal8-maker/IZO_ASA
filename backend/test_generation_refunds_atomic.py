"""The reversal receipt and all balance writes share one transaction."""
from contextlib import closing
import json
import sqlite3

import pytest
import main


def test_failed_refund_receipt_rolls_back_reversal_but_keeps_prior_caller_work(monkeypatch):
    monkeypatch.delenv("IZO_PREPROD_PRESERVE_HISTORY", raising=False)
    main.init_db()
    with closing(main.db()) as conn, conn:
        conn.execute("INSERT INTO users (id, role, token_balance, created_at, last_login_at) VALUES ('refund-user', 'user', 9, 'now', 'now')")
        conn.execute(
            "INSERT INTO token_ledger (id,user_id,delta,reason,meta_json,created_at) VALUES ('charge','refund-user',-1,'generation',?,'now')",
            (json.dumps({"jobId": "job-%-a", "token_cost": 1, "daily_part": 0, "balance_part": 1}, separators=(",", ":")),),
        )
        conn.execute("CREATE TRIGGER reject_refund BEFORE INSERT ON generation_refunds BEGIN SELECT RAISE(ABORT, 'receipt failed'); END")
    with closing(main.db()) as conn, conn:
        conn.execute("UPDATE users SET display_name='prior caller work' WHERE id='refund-user'")
        with pytest.raises(sqlite3.IntegrityError, match="receipt failed"):
            main.refund_generation_tokens(conn, "job-%-a", reason="provider failure")
        assert conn.execute("SELECT token_balance,display_name FROM users WHERE id='refund-user'").fetchone()[:] == (9, "prior caller work")
        assert conn.execute("SELECT COUNT(*) FROM token_ledger WHERE user_id='refund-user'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM generation_refunds").fetchone()[0] == 0
    with closing(main.db()) as conn, conn:
        conn.execute("DROP TRIGGER reject_refund")
        assert not main.refund_generation_tokens(conn, "job-ANY-a", reason="different identity")
        assert main.refund_generation_tokens(conn, "job-%-a", reason="retry")
        assert not main.refund_generation_tokens(conn, "job-%-a", reason="again")
    with closing(main.db()) as conn:
        assert conn.execute("SELECT token_balance FROM users WHERE id='refund-user'").fetchone()[0] == 10
        assert conn.execute("SELECT COUNT(*) FROM generation_refunds").fetchone()[0] == 1
