"""Real API/Phone projections keep worker progress and session ownership."""

from __future__ import annotations

from contextlib import closing

import pytest
from fastapi.testclient import TestClient

import main


def _session(user_id):
    internal_id = "internal-" + user_id
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id,internal_user_id,role,token_balance,created_at,last_login_at) VALUES (?,?,'user',77,?,?)",
            (user_id, internal_id, "2026-10-18T00:00:00+00:00", "2026-10-18T00:00:00+00:00"),
        )
    return main.create_auth_session(internal_id, user_id, provider="web_email", platform="web_desktop")["session_token"]


@pytest.mark.parametrize(("state", "progress", "expected"), [
    ("uploading", 12, "processing"),
    ("sent_to_comfyui", 24, "running"),
    ("sent_to_openrouter", 68, "running"),
])
@pytest.mark.parametrize("cached", [True, False], ids=["live-job", "durable-job"])
def test_worker_progress_is_visible_in_owned_api_and_phone_after_cache_loss(monkeypatch, state, progress, expected, cached):
    main.init_db()
    monkeypatch.setattr(main, "jobs", {})
    owner, other = _session("progress-owner"), _session("progress-other")
    request = main.GenerateRequest(provider="openrouter" if "openrouter" in state else "comfyui",
                                   mode="text_to_image", prompt="Owned progress fixture")
    job = {"id": "job-phone-progress", "userId": "progress-owner", "mode": request.mode,
           "provider": request.provider, "status": state, "progress": progress,
           "request": request.model_dump(), "createdAt": "2026-10-18T00:00:00+00:00", "tokenCost": 9}
    main.persist_job(job, request)
    if cached:
        main.jobs[job["id"]] = job

    with closing(TestClient(main.app)) as client:
        client.cookies.set(main.TRUSTED_SESSION_COOKIE_NAME, owner)
        direct = client.get("/api/jobs/" + job["id"])
        phone = client.get("/api/phone/v1/jobs/" + job["id"])
        assert direct.status_code == phone.status_code == 200
        assert direct.json()["status"] == state and direct.json()["progress"] == progress
        snapshot = phone.json()["job"]
        assert snapshot["status"] == snapshot["phase"] == expected
        assert snapshot["progress"] == progress and snapshot["terminal"] is False
        active = client.get("/api/phone/v1/jobs?active=true").json()["items"]
        assert len(active) == 1 and active[0]["id"] == job["id"]
        assert active[0]["status"] == expected and active[0]["progress"] == progress

        client.cookies.clear()
        client.headers["X-OneNode-User"] = "progress-owner"
        client.cookies.set("onenode_user", "progress-owner")
        for path in ("/api/jobs/" + job["id"], "/api/phone/v1/jobs/" + job["id"], "/api/phone/v1/jobs"):
            assert client.get(path).status_code == 401

        client.cookies.set(main.TRUSTED_SESSION_COOKIE_NAME, other)
        assert client.get("/api/jobs/" + job["id"]).status_code == 404
        assert client.get("/api/phone/v1/jobs/" + job["id"]).status_code == 404
        assert client.get("/api/phone/v1/jobs").json()["items"] == []

        client.cookies.set(main.TRUSTED_SESSION_COOKIE_NAME, owner)
        job.update(status="completed", progress=100, completedAt="2026-10-18T00:00:01+00:00")
        main.persist_job(job, request)
        completed = client.get("/api/phone/v1/jobs/" + job["id"]).json()["job"]
        assert completed["status"] == "completed" and completed["phase"] == "terminal"
        assert completed["progress"] == 100 and completed["terminal"] is True
        assert client.get("/api/phone/v1/jobs?active=true").json()["items"] == []

    with main.db() as conn:
        assert conn.execute("SELECT token_balance FROM users WHERE id='progress-owner'").fetchone()[0] == 77
        assert conn.execute("SELECT COUNT(*) FROM token_ledger").fetchone()[0] == 0
