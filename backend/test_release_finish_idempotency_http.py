"""Real application HTTP admission, trusted sessions and atomic accounting."""
from __future__ import annotations

import json
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
import uvicorn

import main
from app.security.account_verification import require_social_verification


class RecordingQueue:
    def __init__(self):
        self.items = []

    async def put(self, identity):
        self.items.append(identity)

    def qsize(self):
        return len(self.items)


@pytest.fixture
def admission_app(monkeypatch):
    monkeypatch.delenv("IZO_PREPROD_PRESERVE_HISTORY", raising=False)
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    monkeypatch.setattr(main, "queue", RecordingQueue())
    monkeypatch.setattr(main, "rate_limits", {"hourly": 1, "daily": 1})
    main.jobs.clear()
    main.init_db()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tokens = {}
    with closing(main.db()) as conn, conn:
        for name in ("alice", "bob"):
            conn.execute(
                "INSERT INTO users (id, internal_user_id, role, plan, token_balance, "
                "daily_tokens_used, last_daily_reset, created_at, last_login_at) VALUES (?, ?, 'user', 'mini', 100, 5000, ?, ?, ?)",
                (name, "internal-" + name, today, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
            )
    for name in ("alice", "bob"):
        tokens[name] = main.create_auth_session(
            "internal-" + name, name, provider="web_email", platform="web_desktop",
        )["session_token"]
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(main.app, log_level="critical", lifespan="off", ws="none"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started, "Application HTTP server failed to start"

    def post(key="operation-a", *, user="alice", payload=None, bearer=True):
        body = {"mode": "text_to_image", "prompt": "Synthetic admission test", "seed": 42}
        body.update(payload or {})
        headers = {"Content-Type": "application/json", "Idempotency-Key": key}
        if bearer:
            headers["Authorization"] = "Bearer " + tokens[user]
        request = Request(f"http://127.0.0.1:{port}/api/generate", json.dumps(body).encode(), headers)
        try:
            with urlopen(request, timeout=15) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            return exc.code, json.load(exc)

    try:
        yield post
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive(), "Application HTTP server leaked its thread"
        main.jobs.clear()


def accounting(user="alice"):
    with closing(main.db()) as conn:
        return {
            "jobs": conn.execute("SELECT COUNT(*) FROM jobs WHERE user_id=?", (user,)).fetchone()[0],
            "admissions": conn.execute("SELECT COUNT(*) FROM generation_admissions WHERE user_id=?", (user,)).fetchone()[0],
            "ledger": conn.execute("SELECT COUNT(*) FROM token_ledger WHERE user_id=?", (user,)).fetchone()[0],
            "balance": conn.execute("SELECT token_balance FROM users WHERE id=?", (user,)).fetchone()[0],
        }


@pytest.mark.parametrize("concurrency", [2, 5, 10])
def test_real_http_same_key_has_one_job_charge_and_dispatch(admission_app, concurrency):
    barrier = threading.Barrier(concurrency)

    def send(_):
        barrier.wait(timeout=10)
        return admission_app()

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(send, range(concurrency)))
    assert [status for status, _ in results] == [200] * concurrency, results
    assert len({body["id"] for _, body in results}) == 1
    assert accounting() == {"jobs": 1, "admissions": 1, "ledger": 1, "balance": 99}
    assert main.queue.items == [results[0][1]["id"]]


def test_normalized_replay_bypasses_rate_limit_and_returns_current_result(admission_app):
    status, first = admission_app(payload={"steps": 28})
    assert status == 200, first
    with closing(main.db()) as conn, conn:
        conn.execute("UPDATE jobs SET status='completed', progress=100 WHERE id=?", (first["id"],))
    main.jobs.clear()
    status, replay = admission_app(payload={"steps": 4})
    assert status == 200 and replay["id"] == first["id"]
    assert replay["status"] == "completed"
    assert replay["mainBalanceTokenPart"] == first["mainBalanceTokenPart"] == 1
    assert admission_app(key="another-operation")[0] == 429
    assert accounting()["ledger"] == 1


def test_same_key_conflict_and_trusted_identity_isolation(admission_app):
    assert admission_app(payload={"userId": "bob"})[0] == 200
    assert admission_app(payload={"prompt": "Different request"})[0] == 409
    status, bob = admission_app(user="bob")
    assert status == 200 and bob["userId"] == "bob"
    assert accounting("alice")["balance"] == accounting("bob")["balance"] == 99
    assert admission_app(key="unauthorized", bearer=False)[0] == 401


def test_failure_between_charge_and_job_rolls_back_and_allows_retry(admission_app, monkeypatch):
    original = main.persist_job

    def fail_after_charge(*args, **kwargs):
        raise main.HTTPException(503, "synthetic persistence failure")

    monkeypatch.setattr(main, "persist_job", fail_after_charge)
    assert admission_app()[0] == 503
    assert accounting() == {"jobs": 0, "admissions": 0, "ledger": 0, "balance": 100}
    assert main.queue.items == []
    monkeypatch.setattr(main, "persist_job", original)
    assert admission_app()[0] == 200
    assert accounting()["ledger"] == 1


@pytest.mark.parametrize("concurrency", [2, 5, 10])
def test_repeated_concurrent_refunds_and_http_replays_never_charge_again(admission_app, concurrency):
    status, first = admission_app()
    assert status == 200
    barrier = threading.Barrier(concurrency)

    def refund(_):
        barrier.wait(timeout=10)
        with closing(main.db()) as conn, conn:
            return main.refund_generation_tokens(conn, first["id"], reason="synthetic-provider-failure")

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        assert sum(pool.map(refund, range(concurrency))) == 1
    with closing(main.db()) as conn, conn:
        conn.execute("UPDATE jobs SET status='failed', progress=100 WHERE id=?", (first["id"],))
    main.jobs.clear()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(lambda _: admission_app(), range(concurrency)))
    assert all(status == 200 and body["id"] == first["id"] and body["status"] == "failed" for status, body in results)
    assert accounting() == {"jobs": 1, "admissions": 1, "ledger": 2, "balance": 100}
    assert main.queue.items == [first["id"]]


def test_commit_before_enqueue_failure_is_durable_and_recovery_refunds_once(admission_app, monkeypatch):
    async def unavailable_queue(_):
        raise main.HTTPException(503, "synthetic dispatch interruption")

    monkeypatch.setattr(main.queue, "put", unavailable_queue)
    assert admission_app()[0] == 503
    assert accounting() == {"jobs": 1, "admissions": 1, "ledger": 1, "balance": 99}
    main.reconcile_stale_generation_state()
    main.reconcile_stale_generation_state()
    status, replay = admission_app()
    assert status == 200 and replay["status"] == "failed"
    assert accounting() == {"jobs": 1, "admissions": 1, "ledger": 2, "balance": 100}
    assert main.queue.items == []


def test_trial_admission_replays_zero_cost_without_second_reservation(admission_app):
    with closing(main.db()) as conn, conn:
        require_social_verification(conn, "internal-alice", now=datetime.now(timezone.utc).isoformat())
    status, first = admission_app()
    assert status == 200 and first["tokenCost"] == 0, first
    assert first["trialAccess"]["trial_generations_remaining"] == 4
    status, replay = admission_app()
    assert status == 200 and replay["id"] == first["id"] and replay["tokenCost"] == 0
    assert accounting() == {"jobs": 1, "admissions": 1, "ledger": 0, "balance": 100}
    with closing(main.db()) as conn:
        rows = conn.execute("SELECT job_id,state FROM generation_trial_reservations WHERE internal_user_id=?", ("internal-alice",)).fetchall()
        assert [tuple(row) for row in rows] == [(first["id"], "reserved")]
    assert main.queue.items == [first["id"]]


def test_replay_skips_implicit_tariff_reconciliation(admission_app, monkeypatch):
    status, first = admission_app()
    assert status == 200

    def forbidden_reconciliation(_):
        pytest.fail("Replay attempted tariff mutation")

    monkeypatch.setattr(main, "expire_paid_plan_if_needed", forbidden_reconciliation)
    status, replay = admission_app()
    assert status == 200 and replay["id"] == first["id"]
    assert accounting()["ledger"] == 1


def _committed_trial_with_dispatch_failure(admission_app, monkeypatch):
    with closing(main.db()) as conn, conn:
        require_social_verification(conn, "internal-alice", now=datetime.now(timezone.utc).isoformat())

    async def unavailable_queue(_):
        raise main.HTTPException(503, "synthetic trial dispatch interruption")

    monkeypatch.setattr(main.queue, "put", unavailable_queue)
    assert admission_app()[0] == 503
    assert accounting() == {"jobs": 1, "admissions": 1, "ledger": 0, "balance": 100}
    with closing(main.db()) as conn:
        row = conn.execute(
            "SELECT jobs.id, jobs.status, reservation.state, reservation.settled_at "
            "FROM jobs JOIN generation_trial_reservations AS reservation ON reservation.job_id=jobs.id "
            "WHERE jobs.user_id='alice' AND reservation.internal_user_id='internal-alice'",
        ).fetchone()
    assert row is not None
    assert (row["status"], row["state"], row["settled_at"]) == ("queued", "reserved", None)
    main.jobs.clear()
    return str(row["id"])


def _trial_recovery_state(job_id):
    with closing(main.db()) as conn:
        row = conn.execute(
            "SELECT jobs.status, jobs.completed_at, jobs.result_image_id, "
            "reservation.state, reservation.settled_at "
            "FROM jobs JOIN generation_trial_reservations AS reservation ON reservation.job_id=jobs.id "
            "WHERE jobs.id=?",
            (job_id,),
        ).fetchone()
        trial = main.get_social_verification(conn, "internal-alice", now=datetime.now(timezone.utc).isoformat())
        refunds = conn.execute("SELECT COUNT(*) FROM generation_refunds WHERE job_id=?", (job_id,)).fetchone()[0]
    assert row is not None and trial is not None
    return dict(row), trial, refunds


def test_trial_recovery_releases_committed_reservation_once_after_dispatch_failure(admission_app, monkeypatch):
    job_id = _committed_trial_with_dispatch_failure(admission_app, monkeypatch)
    first = main.reconcile_stale_generation_state()
    assert first == {"checked": 1, "completed_from_images": 0, "failed": 1, "refunds_created": 0}
    settled, trial, refunds = _trial_recovery_state(job_id)
    assert settled["status"] == "failed" and settled["state"] == "released"
    assert settled["completed_at"]
    assert settled["settled_at"] == settled["completed_at"]
    assert settled["result_image_id"] is None
    assert trial["trial_generations_reserved"] == trial["trial_generations_consumed"] == 0
    assert trial["trial_generations_remaining"] == 5
    assert refunds == 0

    second = main.reconcile_stale_generation_state()
    assert second == {"checked": 0, "completed_from_images": 0, "failed": 0, "refunds_created": 0}
    assert _trial_recovery_state(job_id)[0] == settled
    for _ in range(2):
        status, replay = admission_app()
        assert status == 200 and replay["id"] == job_id and replay["status"] == "failed"
        assert replay["tokenCost"] == 0
    assert _trial_recovery_state(job_id)[0] == settled
    assert accounting() == {"jobs": 1, "admissions": 1, "ledger": 0, "balance": 100}
    assert main.queue.items == []


def test_trial_recovery_consumes_reservation_once_when_output_is_already_saved(admission_app, monkeypatch):
    job_id = _committed_trial_with_dispatch_failure(admission_app, monkeypatch)
    image_id = "synthetic-recovered-trial-image"
    image_url = "/api/media/synthetic-recovered-trial.png"
    image_created_at = datetime.now(timezone.utc).isoformat()
    with closing(main.db()) as conn, conn:
        conn.execute("UPDATE jobs SET status='sent_to_comfyui',progress=80 WHERE id=?", (job_id,))
        conn.execute(
            "INSERT INTO images (id,user_id,job_id,url,thumbnail_url,width,height,mode,provider,created_at) "
            "VALUES (?,'alice',?,?,'',32,32,'text_to_image','comfyui',?)",
            (image_id, job_id, image_url, image_created_at),
        )

    first = main.reconcile_stale_generation_state()
    assert first == {"checked": 1, "completed_from_images": 1, "failed": 0, "refunds_created": 0}
    settled, trial, refunds = _trial_recovery_state(job_id)
    assert settled == {
        "status": "completed", "completed_at": image_created_at, "result_image_id": image_id,
        "state": "consumed", "settled_at": image_created_at,
    }
    assert trial["trial_generations_reserved"] == 0
    assert trial["trial_generations_consumed"] == 1
    assert trial["trial_generations_remaining"] == 4
    assert refunds == 0

    second = main.reconcile_stale_generation_state()
    assert second == {"checked": 0, "completed_from_images": 0, "failed": 0, "refunds_created": 0}
    assert _trial_recovery_state(job_id)[0] == settled
    for _ in range(2):
        status, replay = admission_app()
        assert status == 200 and replay["id"] == job_id and replay["status"] == "completed"
        assert replay["tokenCost"] == 0
        assert replay["resultImageId"] == image_id and replay["resultUrl"] == image_url
    assert _trial_recovery_state(job_id)[0] == settled
    assert accounting() == {"jobs": 1, "admissions": 1, "ledger": 0, "balance": 100}
    assert main.queue.items == []
