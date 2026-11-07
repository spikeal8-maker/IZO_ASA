"""Restored-history boundaries exercised through the actual application routes."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import main
from app.billing.outbox import OutboxMessage
from app.services.history_replay import (
    HistoricalReplayBlocked, HistoryReplayConfigurationError, seal_restored_history,
)


def fingerprints():
    result = {}
    with closing(main.db()) as conn:
        for table in ("jobs", "images", "image_sources", "videos", "video_sources", "token_ledger", "payments", "invoices",
                      "payment_notification_outbox", "payment_provider_events", "social_delivery_outbox", "feed_publications",
                      "account_verifications", "generation_trial_reservations", "video_file_deletions", "billing_packages"):
            rows = [tuple(row) for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
            result[table] = hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()
        result["wallets"] = [tuple(row) for row in conn.execute(
            "SELECT id,token_balance,daily_tokens_used,tokens_used,generation_count,plan,"
            "plan_next_token_grant_at,plan_expires_at FROM users ORDER BY id"
        )]
    return result


@pytest.fixture
def restored_history(monkeypatch):
    monkeypatch.delenv("IZO_PREPROD_PRESERVE_HISTORY", raising=False)
    monkeypatch.delenv("IZO_HISTORY_SNAPSHOT_ID", raising=False)
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    monkeypatch.setattr(main, "worker_started", True)
    main.init_db()
    now = datetime.now(timezone.utc).isoformat()
    with closing(main.db()) as conn, conn:
        for name, role in (("old-user", "user"), ("other-user", "user"), ("old-admin", "admin")):
            conn.execute(
                "INSERT INTO users (id,internal_user_id,role,plan,token_balance,created_at,last_login_at,"
                "plan_started_at,plan_expires_at,plan_next_token_grant_at,plan_monthly_token_grant) "
                "VALUES (?,? ,?,'mini',123,?,?,'2020-01-01T00:00:00+00:00','2099-01-01T00:00:00+00:00',"
                "'2020-02-01T00:00:00+00:00',50)",
                (name, "internal-" + name, role, now, now),
            )
        for identity, status, mode, provider in (
            ("old-queued", "queued", "text_to_image", "comfyui"),
            ("old-running", "running", "text_to_image", "comfyui"),
            ("old-video", "pending", "text_to_video", "local_ltx"),
        ):
            conn.execute(
                "INSERT INTO jobs (id,user_id,mode,provider,status,progress,settings_json,created_at) "
                "VALUES (?,'old-user',?,?,?,?,?,?)",
                (identity, mode, provider, status, 10, json.dumps({"comfyPromptId": "old-provider-id"}), now),
            )
        conn.execute(
            "INSERT INTO images (id,user_id,job_id,url,thumbnail_url,width,height,mode,provider,created_at) "
            "VALUES ('old-image','old-user','old-queued','/api/media/old.png','',32,32,'text_to_image','comfyui',?)", (now,),
        )
        conn.execute(
            "UPDATE jobs SET settings_json=? WHERE id='old-queued'",
            (json.dumps({"mode": "image_to_image", "provider": "comfyui", "prompt": "source recovery",
                         "inputImage1": "/api/media/source.png"}),),
        )
        conn.execute(
            "INSERT INTO token_ledger (id,user_id,delta,reason,meta_json,created_at) "
            "VALUES ('old-charge','old-user',-1,'generation',?,?)",
            (json.dumps({"jobId": "old-running", "token_cost": 1, "balance_part": 1}), now),
        )
        conn.execute(
            "INSERT INTO invoices (id,invoice_code,internal_user_id,user_id,status,total_amount,tokens_total,created_at,updated_at) "
            "VALUES ('old-invoice','OLD-1','internal-old-user','old-user','issued',100,50,?,?)", (now, now),
        )
        conn.execute(
            "INSERT INTO payments (id,invoice_id,internal_user_id,user_id,status,amount,provider,provider_payment_id,created_at,updated_at) "
            "VALUES ('old-payment','old-invoice','internal-old-user','old-user','pending',100,'yookassa','old-external',?,?)", (now, now),
        )
        conn.execute(
            "INSERT INTO video_file_deletions (id,filename,created_at) VALUES ('old-deletion','retained.bin',?)", (now,),
        )
        main.enqueue_payment_notification(
            conn, payment_id="old-payment", internal_user_id="internal-old-user",
            event_type="payment_success", channel="email", destination="synthetic@example.invalid",
            payload={}, now=now,
        )
        seal_restored_history(conn, snapshot_id="test-restored-snapshot")
    (main.MEDIA / "retained.bin").write_bytes(b"must survive old deletion queue")
    monkeypatch.setenv("IZO_PREPROD_PRESERVE_HISTORY", "1")
    monkeypatch.setenv("IZO_HISTORY_SNAPSHOT_ID", "test-restored-snapshot")
    sessions = {
        name: main.create_auth_session("internal-" + name, name, provider="web_email", platform="web_desktop")["session_token"]
        for name in ("old-user", "other-user", "old-admin")
    }
    main.jobs.clear()
    main.images.clear()
    return sessions


def headers(sessions, name="old-user"):
    return {"Authorization": "Bearer " + sessions[name]}


def test_opening_historical_sections_never_reconciles_or_contacts_providers(restored_history, monkeypatch):
    async def forbidden_provider(*args, **kwargs):
        pytest.fail("Historical browsing attempted provider I/O")

    monkeypatch.setattr(main, "fetch_yookassa_payment", forbidden_provider)
    monkeypatch.setattr(main, "poll_openrouter_video", forbidden_provider)
    monkeypatch.setattr(main.ltx_video.ComfyLtxClient, "status", forbidden_provider)
    monkeypatch.setattr(main, "yookassa_checkout_ready", lambda *args: True)
    before = fingerprints()
    client = TestClient(main.app)
    for _ in range(2):
        main.init_db()
        main.load_db_state()
        main.reconcile_stale_generation_state()
        for path in (
            "/api/me-v2", "/api/me/profile-v2", "/api/gallery", "/api/gallery/items",
            "/api/gallery/page", "/api/video/history", "/api/video/jobs/old-video",
            "/api/billing/payments/old-payment/status-v2", "/api/billing/packages-v2",
        ):
            response = client.get(path, headers=headers(restored_history))
            assert response.status_code == 200, (path, response.status_code, response.text)
        response = client.get("/api/admin/users-v2", headers=headers(restored_history, "old-admin"))
        assert response.status_code == 200, response.text
        assert fingerprints() == before
    assert client.get("/api/gallery", headers=headers(restored_history, "other-user")).json() == []
    assert client.get("/api/jobs/old-running", headers=headers(restored_history, "other-user")).status_code == 404
    assert client.get("/api/admin/users-v2", headers=headers(restored_history)).status_code == 403
    monkeypatch.setattr(main, "yookassa_ready", lambda *args: True)
    response = client.post("/api/billing/yookassa/webhook-v2", json={
        "event": "payment.succeeded", "object": {"id": "old-external"},
    })
    assert response.status_code == 200 and response.json()["historical"] is True
    assert fingerprints() == before


def test_old_recovery_refunds_payments_and_deletion_are_fenced(restored_history):
    before = fingerprints()
    with closing(main.db()) as conn, conn:
        with pytest.raises(HistoricalReplayBlocked):
            main.refund_generation_tokens(conn, "old-running", reason="repeated recovery")
        assert main._reconcile_user_tariff(conn, "internal-old-user")["changed"] is False
    with pytest.raises(HistoricalReplayBlocked):
        main._complete_provider_payment("yookassa", "old-external", verified_amount="100.00", verified_currency="RUB")
    with pytest.raises(HistoricalReplayBlocked):
        main._cancel_provider_payment("yookassa", "old-external")
    assert main.drain_video_file_deletions()["checked"] == 0
    assert (main.MEDIA / "retained.bin").read_bytes() == b"must survive old deletion queue"
    assert fingerprints() == before


def test_historical_gallery_detail_never_repairs_sources_but_new_images_can(restored_history, monkeypatch):
    restored = []

    def restore_new_only(image_id, user_id, request, created_at):
        assert image_id == "new-image", "Historical gallery GET attempted to persist source media"
        assert user_id == "old-user" and request.inputImage1 == "/api/media/source.png"
        restored.append(image_id)
        return [{"id": "new-source", "imageId": image_id}]

    monkeypatch.setattr(main, "persist_image_sources", restore_new_only)
    before = fingerprints()
    media_before = {str(path.relative_to(main.MEDIA)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in main.MEDIA.rglob("*") if path.is_file()}
    client = TestClient(main.app)
    for _ in range(2):
        response = client.get("/api/gallery/old-image", headers=headers(restored_history))
        assert response.status_code == 200, response.text
        assert response.json()["sources"] == []
    assert client.get("/api/gallery/old-image", headers=headers(restored_history, "other-user")).status_code == 404
    assert restored == []
    assert fingerprints() == before
    assert {str(path.relative_to(main.MEDIA)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in main.MEDIA.rglob("*") if path.is_file()} == media_before

    now = datetime.now(timezone.utc).isoformat()
    with closing(main.db()) as conn, conn:
        conn.execute(
            "INSERT INTO jobs (id,user_id,mode,provider,status,progress,settings_json,created_at) "
            "SELECT 'new-job',user_id,mode,provider,'completed',100,settings_json,? "
            "FROM jobs WHERE id='old-queued'", (now,),
        )
        conn.execute(
            "INSERT INTO images (id,user_id,job_id,url,thumbnail_url,width,height,mode,provider,created_at) "
            "VALUES ('new-image','old-user','new-job','/api/media/new.png','',32,32,'image_to_image','comfyui',?)", (now,),
        )
    response = client.get("/api/gallery/new-image", headers=headers(restored_history))
    assert response.status_code == 200, response.text
    assert response.json()["sources"] == [{"id": "new-source", "imageId": "new-image"}]
    assert restored == ["new-image"]


def test_history_mode_without_seal_fails_before_legacy_initialization(monkeypatch):
    monkeypatch.delenv("IZO_PREPROD_PRESERVE_HISTORY", raising=False)
    main.init_db()
    before = fingerprints()
    monkeypatch.setenv("IZO_PREPROD_PRESERVE_HISTORY", "1")
    with pytest.raises(HistoryReplayConfigurationError):
        main.init_db()
    assert fingerprints() == before


def test_preserved_startup_does_not_start_external_or_destructive_workers(restored_history, monkeypatch):
    def forbidden_start(*args, **kwargs):
        pytest.fail("Preserved startup attempted external or destructive worker")

    for worker in (main.ADMIN_NOTIFICATION_DELIVERY_WORKER, main.SOCIAL_DELIVERY_WORKER,
                   main.energy_telemetry.POWER_TELEMETRY_WORKER, main.assistant_runtime.OLLAMA_RESIDENCY):
        monkeypatch.setattr(worker, "start", forbidden_start)
    monkeypatch.setattr(main.ACCOUNT_RETENTION_WORKER, "start_with_cleanup", forbidden_start)
    monkeypatch.setattr(main, "start_bot_workers", forbidden_start)
    monkeypatch.setattr(main, "migrate_openrouter_secret_from_sqlite", forbidden_start)
    before = fingerprints()

    async def lifecycle():
        for _ in range(2):
            await main.startup()
            await main.shutdown()
            await main.GENERATION_CONSUMER.stop()

    asyncio.run(lifecycle())
    assert fingerprints() == before


def test_seal_cannot_be_replaced_even_with_sqlite_replace(restored_history):
    with closing(main.db()) as conn, conn:
        row = tuple(conn.execute("SELECT * FROM history_replay_boundary").fetchone())
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("INSERT OR REPLACE INTO history_replay_boundary VALUES (?,?,?,?,?)", row)
        assert tuple(conn.execute("SELECT * FROM history_replay_boundary").fetchone()) == row


def test_stale_claim_is_rechecked_before_payment_email_transport(restored_history, monkeypatch):
    with closing(main.db()) as conn:
        row = conn.execute("SELECT * FROM payment_notification_outbox WHERE payment_id='old-payment'").fetchone()
    message = OutboxMessage(
        id=row["id"], payment_id=row["payment_id"], internal_user_id=row["internal_user_id"],
        event_type=row["event_type"], channel=row["channel"], destination=row["destination"],
        attempts=row["attempts"], payload={},
    )
    monkeypatch.setattr(main, "claim_payment_notifications", lambda *args, **kwargs: [message])
    monkeypatch.setattr(main, "email_provider_configured", lambda: True)

    def forbidden_send(*args, **kwargs):
        pytest.fail("A stale historical payment claim reached SMTP")

    monkeypatch.setattr(main, "send_transactional_email", forbidden_send)
    before = fingerprints()
    response = TestClient(main.app).post(
        "/api/admin/payments/notifications/process-v2", json={"limit": 10, "reason": "verify history guard"},
        headers=headers(restored_history, "old-admin"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["sent"] == response.json()["retried"] == 0
    assert fingerprints() == before
