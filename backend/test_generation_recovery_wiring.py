from __future__ import annotations

import inspect
import json
import uuid

import main


def test_main_reconciliation_uses_existing_idempotent_refund() -> None:
    job_id = "job-startup-recovery"
    user_id = "web-startup-recovery"
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

    report = main.reconcile_stale_generation_state()

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
    assert job["status"] == "failed" and job["progress"] == 100 and job["completed_at"]
    assert job["error_message"] == main.generation_recovery.STARTUP_INTERRUPTION_MESSAGE
    assert dict(user) == {"token_balance": 100, "tokens_used": 0, "generation_count": 0}
    assert refund["delta"] == 3 and json.loads(refund["meta_json"])["reason"] == "startup_reconciliation"


def test_startup_reconciles_before_loading_in_memory_jobs() -> None:
    source = inspect.getsource(main.startup)

    assert source.index("reconcile_stale_generation_state()") < source.index("load_db_state()")
