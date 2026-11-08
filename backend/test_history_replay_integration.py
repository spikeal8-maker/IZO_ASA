"""Real service entry points with synthetic restored state and fake transports."""
from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import main
from app.billing import outbox
from app.services import account_retention, admin_notification_delivery as admin
from app.services import generation_recovery, generation_queue, generation_worker
from app.services import social_delivery as social
from app.services.history_replay import (
    HistoricalReplayBlocked,
    HistoryReplayConfigurationError,
    seal_restored_history,
)
from app.services.ltx_video import orchestration as ltx
from test_history_replay import install_schema
from test_services_generation_queue_module import FakeQueue, QueueExhausted, runtime as queue_runtime
from test_services_generation_worker_module import Harness, base_job, request

OLD = "2020-01-01T00:00:00+00:00"
NOW = datetime(2026, 11, 8, tzinfo=timezone.utc)


def insert(conn, table, **values):
    for column in conn.execute(f'PRAGMA table_info("{table}")'):
        name, kind, required, default = column[1:5]
        if required and default is None and name not in values:
            values[name] = OLD if name.endswith("_at") else (0 if "INT" in kind else "synthetic-" + name)
    columns = ",".join('"' + name + '"' for name in values)
    placeholders = ",".join("?" for _ in values)
    conn.execute(f'INSERT INTO "{table}" ({columns}) VALUES ({placeholders})', tuple(values.values()))


def seed_deliveries(conn, prefix):
    insert(conn, "payments", id=prefix+"-payment", invoice_id="synthetic-invoice",
           internal_user_id="old-i", status="pending")
    insert(conn, "admin_notifications", id=prefix+"-notification", dedupe_key=prefix,
           category="generation", severity="info", title=prefix, message=prefix)
    insert(conn, "images", id=prefix+"-image", user_id="old-u", url="/synthetic.png",
           thumbnail_url="/synthetic-thumb.png", width=1, height=1, mode="text_to_image", provider="comfyui")
    insert(conn, "feed_publications", id=prefix+"-publication", image_id=prefix+"-image", internal_user_id="old-i",
           title=prefix, media_type="image", status="published", media_ready_at=OLD)
    insert(conn, "payment_notification_outbox", id=prefix+"-payment-notice",
           payment_id=prefix+"-payment", internal_user_id="old-i", event_type="paid",
           channel="email", status="pending", next_attempt_at=OLD, payload_json="{}")
    insert(conn, "admin_notification_delivery_outbox", id=prefix+"-admin",
           notification_id=prefix+"-notification", channel="telegram",
           destination="synthetic", status="pending", next_attempt_at=OLD, payload_json="{}")
    for network in ("telegram", "max", "delete_max"):
        insert(conn, "social_delivery_outbox", id=prefix+"-"+network,
               publication_id=prefix+"-publication", network=network,
               status="pending", next_attempt_at=OLD, external_id="synthetic")


@pytest.fixture
def restored(monkeypatch):
    monkeypatch.setenv("IZO_PREPROD_PRESERVE_HISTORY", "0")
    main.init_db()
    conn = main.db()
    conn.execute("PRAGMA journal_mode=WAL")
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='history_replay_boundary'").fetchone():
        install_schema(conn)
    insert(conn, "users", id="old-u", internal_user_id="old-i",
           role="user", token_balance=100)
    insert(conn, "token_ledger", id="old-ledger", user_id="old-u",
           delta=100, reason="historical")
    insert(conn, "jobs", id="old-job", user_id="old-u",
           mode="text_to_image", provider="comfyui", status="queued")
    insert(conn, "jobs", id="old-ltx", user_id="old-u", mode="text_to_video",
           provider="local_ltx", status="queued", settings_json='{"comfyPromptId":"old-prompt"}')
    insert(conn, "account_verifications", internal_user_id="old-i",
           verification_kind="social", status="pending", required_at=OLD,
           remind_after_at=OLD, delete_after_at=OLD)
    seed_deliveries(conn, "old")
    conn.commit()
    policy = seal_restored_history(conn, snapshot_id="synthetic-integration")
    conn.commit()
    monkeypatch.setenv("IZO_PREPROD_PRESERVE_HISTORY", "1")
    monkeypatch.setenv("IZO_HISTORY_SNAPSHOT_ID", "synthetic-integration")
    yield SimpleNamespace(conn=conn, policy=policy)
    conn.close()


def rows(conn, table):
    return [tuple(row) for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY 1')]


@pytest.mark.parametrize("status", ["pending", "processing", "retry"])
def test_old_payment_claim_and_late_callbacks_leave_rows_unchanged(restored, status):
    conn = restored.conn
    conn.execute("UPDATE payment_notification_outbox SET status=?", (status,))
    conn.commit()
    before = rows(conn, "payment_notification_outbox")
    assert outbox.pending_messages(conn, now=NOW.isoformat()) == []
    assert outbox.claim_pending_messages(conn, now=NOW) == []
    outbox.mark_sent(conn, "old-payment-notice")
    outbox.mark_retry(conn, "old-payment-notice", "late failure")
    assert rows(conn, "payment_notification_outbox") == before


@pytest.mark.parametrize("kind", ["admin", "telegram", "max", "deletion"])
def test_old_delivery_batches_never_call_transport_or_mutate(restored, kind):
    conn = restored.conn
    calls = []

    async def send(*args):
        calls.append(args)
        return "synthetic"

    before_admin = rows(conn, "admin_notification_delivery_outbox")
    before_social = rows(conn, "social_delivery_outbox")
    if kind == "admin":
        report = asyncio.run(admin.deliver_pending_batch(
            conn, send_telegram=send, send_email=send, now=NOW,
        ))
        admin.mark_delivery_sent(conn, "old-admin")
        admin.mark_delivery_retry(conn, "old-admin", "late")
    elif kind == "telegram":
        report = asyncio.run(social.deliver_pending_telegram_batch(conn, send_telegram=send, now=NOW))
    elif kind == "max":
        report = asyncio.run(social.deliver_pending_social_batch(conn, network="max", sender=send, now=NOW))
    else:
        report = asyncio.run(social.deliver_pending_social_deletion_batch(conn, sender=send, now=NOW))
    social.mark_social_delivery_sent(conn, "old-telegram", external_id="late")
    social.mark_social_delivery_retry(conn, "old-telegram", "late")
    assert report == {"claimed": 0, "sent": 0, "retried": 0, "failed": 0}
    assert calls == []
    assert rows(conn, "admin_notification_delivery_outbox") == before_admin
    assert rows(conn, "social_delivery_outbox") == before_social


def test_new_outgoing_work_for_historical_user_is_allowed(restored):
    conn = restored.conn
    seed_deliveries(conn, "new")
    conn.commit()
    assert [m.id for m in outbox.claim_pending_messages(conn, now=NOW)] == ["new-payment-notice"]
    outbox.mark_sent(conn, "new-payment-notice")
    conn.commit()
    sent = []

    async def admin_send(delivery):
        sent.append(delivery.id)
        return "synthetic-admin"

    async def social_send(delivery, _publication):
        sent.append(delivery.id)
        return "synthetic-social", None

    assert asyncio.run(admin.deliver_pending_batch(
        conn, send_telegram=admin_send, send_email=admin_send, now=NOW,
    ))["sent"] == 1
    report = asyncio.run(social.deliver_pending_telegram_batch(
        conn, send_telegram=social_send, now=NOW,
    ))
    assert report["sent"] == 1, (report, [tuple(r) for r in conn.execute("SELECT id, status, last_error FROM social_delivery_outbox")])
    assert sent == ["new-admin", "new-telegram"]
    assert conn.execute("SELECT status FROM payment_notification_outbox WHERE id='old-payment-notice'").fetchone()[0] == "pending"


def test_new_outbox_children_of_historical_parents_cannot_be_claimed(restored):
    conn = restored.conn
    insert(conn, "payment_notification_outbox", id="new-child-payment",
           payment_id="old-payment", internal_user_id="old-i", event_type="refund",
           channel="email", status="pending", next_attempt_at=OLD, payload_json="{}")
    insert(conn, "admin_notification_delivery_outbox", id="new-child-admin",
           notification_id="old-notification", channel="email", destination="other",
           status="pending", next_attempt_at=OLD, payload_json="{}")
    insert(conn, "social_delivery_outbox", id="new-child-social",
           publication_id="old-publication", network="vk", status="pending", next_attempt_at=OLD)
    conn.commit()
    assert outbox.claim_pending_messages(conn, now=NOW) == []
    assert admin.claim_pending_deliveries(conn, now=NOW) == []
    assert social.claim_pending_social_deliveries(conn, network="vk", now=NOW) == []
    with pytest.raises(HistoricalReplayBlocked):
        outbox.enqueue_payment_notification(
            conn, payment_id="old-payment", internal_user_id="old-i", event_type="another",
            channel="email", destination=None, payload={},
        )
    with pytest.raises(HistoricalReplayBlocked):
        admin.enqueue_configured_admin_deliveries(
            conn, notification_id="old-notification", category="generation",
            severity="info", title="old", message="old", action_url=None, created_at=OLD,
        )
    with pytest.raises(HistoricalReplayBlocked):
        social.enqueue_social_deletions(conn, "old-publication")


def test_defensive_delivery_guard_rejects_stale_claim_before_send(restored, monkeypatch):
    conn = restored.conn
    delivery = admin.AdminDelivery("old-admin", "old-notification", "telegram", "synthetic", 0, {})
    monkeypatch.setattr(admin, "claim_pending_deliveries", lambda *a, **k: [delivery])
    sent = []

    async def send(item):
        sent.append(item)

    before = rows(conn, "admin_notification_delivery_outbox")
    assert asyncio.run(admin.deliver_pending_batch(
        conn, send_telegram=send, send_email=send, now=NOW,
    ))["sent"] == 0
    assert sent == []
    assert rows(conn, "admin_notification_delivery_outbox") == before


@pytest.mark.parametrize("with_new", [False, True])
def test_recovery_does_not_refund_old_jobs_but_new_recovery_remains_available(restored, with_new):
    conn = restored.conn
    if with_new:
        insert(conn, "jobs", id="new-job", user_id="old-u",
               mode="text_to_image", provider="comfyui", status="running")
        conn.commit()
    old_ledger = rows(conn, "token_ledger")
    refunds = []

    def refund(db, job_id, *, reason):
        refunds.append(job_id)
        insert(db, "token_ledger", id="refund-"+job_id, user_id="old-u",
               delta=3, reason=reason)
        db.execute("UPDATE users SET token_balance=token_balance+3 WHERE id='old-u'")
        return True

    report = generation_recovery.reconcile_stale_generation_jobs(
        conn, completed_at=NOW.isoformat(), refund_job=refund,
    )
    conn.commit()
    assert refunds == (["new-job"] if with_new else [])
    assert report.refunds_created == int(with_new)
    assert conn.execute("SELECT status FROM jobs WHERE id='old-job'").fetchone()[0] == "queued"
    assert conn.execute("SELECT token_balance FROM users WHERE id='old-u'").fetchone()[0] == 100 + 3 * with_new
    assert rows(conn, "token_ledger")[:1] == old_ledger


def test_queue_skips_old_record_without_request_and_keeps_processing(restored):
    queue = FakeQueue("old-job", "new-job")
    calls = []

    async def process(job_id, *_args, **_kwargs):
        calls.append(job_id)

    runtime = replace(queue_runtime(
        queue, jobs={"old-job": {"status": "queued"}, "new-job": {"request": {"prompt": "new"}}},
        process_job=process,
    ), history_guard=lambda job_id: restored.policy.require_allowed("jobs", job_id), history_guard_required=True)
    with pytest.raises(QueueExhausted):
        asyncio.run(generation_queue.consume_generation_queue(runtime))
    assert calls == ["new-job"]
    assert queue.task_done_calls == 2


@pytest.mark.parametrize("status", ["queued", "cancelled", "running"])
def test_worker_old_job_never_enters_provider_or_refund_catch(restored, status):
    harness = Harness()
    job = {**base_job(status=status), "id": "old-job"}
    runtime = replace(harness.runtime(),
                      history_guard=lambda job_id: restored.policy.require_allowed("jobs", job_id),
                      history_guard_required=True)
    asyncio.run(generation_worker.process_generation_job("old-job", job, request(), runtime, started_at=0))
    assert harness.events == []
    assert job["status"] == status


def test_worker_new_job_for_old_user_still_completes_with_fake_provider(restored):
    harness = Harness()
    job = {**base_job(), "id": "new-job", "userId": "old-u"}
    runtime = replace(harness.runtime(),
                      history_guard=lambda job_id: restored.policy.require_allowed("jobs", job_id),
                      history_guard_required=True)
    asyncio.run(generation_worker.process_generation_job("new-job", job, request(), runtime, started_at=0))
    assert job["status"] == "completed"
    assert harness.refunds == []
    assert len(harness.saved) == 1


def test_required_but_missing_runtime_guard_fails_before_side_effects():
    harness = Harness()
    with pytest.raises(HistoryReplayConfigurationError):
        asyncio.run(generation_worker.process_generation_job(
            "old-job", base_job(), request(),
            replace(harness.runtime(), history_guard_required=True), started_at=0,
        ))
    assert harness.events == []
    queue = FakeQueue("job_1")
    with pytest.raises(HistoryReplayConfigurationError):
        asyncio.run(generation_queue.consume_generation_queue(
            replace(queue_runtime(queue), history_guard_required=True),
        ))
    assert queue.task_done_calls == 1


def test_old_due_password_account_survives_login_and_cleanup(restored):
    conn = restored.conn
    before_user = rows(conn, "users")
    before_ledger = rows(conn, "token_ledger")
    before_verification = rows(conn, "account_verifications")
    state, outcome = account_retention.enforce_due_unverified_login(main.db, "old-i", now=NOW.isoformat())
    assert state["social_verification_deletion_due"]
    assert outcome == "protected"
    assert account_retention.cleanup_due_unverified_accounts(main.db, now=NOW.isoformat())["checked"] == 0
    assert rows(conn, "users") == before_user
    assert rows(conn, "token_ledger") == before_ledger
    assert rows(conn, "account_verifications") == before_verification


def test_ltx_new_request_does_not_probe_or_refund_old_active_job(restored, monkeypatch, tmp_path):
    calls = []

    class Client:
        async def readiness(self):
            return {"ready": True}

        async def status(self, prompt_id):
            calls.append(("old-status", prompt_id))
            return {"status": "missing"}

    async def submit(*args, **kwargs):
        calls.append(("new-submit",))
        return {"id": "new-ltx"}

    monkeypatch.setattr(ltx, "submit_local_ltx_job", submit)
    workflow = tmp_path / "workflow.json"
    workflow.write_text("{}")
    req = SimpleNamespace(mode="text_to_video", generateAudio=False, duration=2, resolution="480p", aspectRatio="16:9")
    result = asyncio.run(ltx.validate_and_submit_local_ltx_job(
        req, user_id="old-u", profile=SimpleNamespace(durations=(2, 4)), workflow_path=workflow,
        client=Client(), open_db=main.db, refund_tokens=lambda *a, **k: calls.append(("refund",)),
    ))
    assert result == {"id": "new-ltx"}
    assert calls == [("new-submit",)]
    assert restored.conn.execute("SELECT status FROM jobs WHERE id='old-ltx'").fetchone()[0] == "queued"
