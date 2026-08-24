from __future__ import annotations

import json
import sqlite3

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.routers.phone_jobs import PhoneJobDependencies, create_phone_jobs_router
from app.services.phone_jobs import list_phone_jobs, normalize_phone_job


def _database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE jobs (
          id TEXT PRIMARY KEY,user_id TEXT,mode TEXT,status TEXT,progress INTEGER,
          error_message TEXT,settings_json TEXT,created_at TEXT,started_at TEXT,completed_at TEXT
        );
        CREATE TABLE images (
          id TEXT PRIMARY KEY,job_id TEXT,user_id TEXT,url TEXT,thumbnail_url TEXT,
          width INTEGER,height INTEGER,deleted_at TEXT,created_at TEXT
        );
        """
    )
    return conn


def test_normalize_phone_job_hides_private_provider_failure() -> None:
    job = normalize_phone_job({
        "id": "job-1", "mode": "text_to_image", "status": "failed", "progress": 17,
        "error": "OpenRouter insufficient credits at private endpoint",
    })
    assert job["terminal"] is True
    assert job["progress"] == 17
    assert "OpenRouter" not in job["message"]
    assert "поддержку" in job["message"]


def test_normalize_phone_job_tolerates_malformed_progress() -> None:
    job = normalize_phone_job({
        "id": "job-bad-progress",
        "mode": "text_to_image",
        "status": "running",
        "progress": "not-a-number",
    })
    assert job["progress"] == 0


def test_normalize_phone_job_maps_private_provider_state_to_public_created() -> None:
    job = normalize_phone_job({
        "id": "job-private-state",
        "mode": "text_to_image",
        "status": "provider_warming_up",
        "progress": 1,
    })
    assert job["status"] == "created"
    assert job["phase"] == "created"


def test_list_phone_jobs_returns_only_owned_active_jobs() -> None:
    conn = _database()
    conn.executemany(
        "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            ("image-1", "user-1", "text_to_image", "running", 42, None, json.dumps({"tokenCost": 1}), "2026-01-01", None, None),
            ("video-1", "user-1", "text_to_video", "completed", 100, None, json.dumps({"tokenCost": 9, "localFile": "v.mp4", "duration": 6, "aspectRatio": "9:16"}), "2026-01-02", None, "2026-01-03"),
            ("other-1", "user-2", "text_to_image", "running", 80, None, "{}", "2026-01-04", None, None),
        ],
    )
    active = list_phone_jobs(conn, "user-1")
    assert [job["id"] for job in active] == ["image-1"]
    all_jobs = list_phone_jobs(conn, "user-1", active_only=False)
    assert [job["id"] for job in all_jobs] == ["video-1", "image-1"]
    assert all_jobs[0]["result"]["url"] == "/api/video/media/video-1"
    assert all_jobs[0]["billing"]["chargedTokens"] == 9


def test_phone_job_route_uses_owned_modality_reader() -> None:
    conn = _database()
    conn.execute(
        "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("video-1", "user-1", "text_to_video", "running", 55, None, "{}", "2026-01-01", None, None),
    )
    calls: list[str] = []

    async def image_reader(_job_id: str, _request: Request):
        calls.append("image")
        return {}

    async def video_reader(job_id: str, _request: Request):
        calls.append("video")
        return {"id": job_id, "mode": "text_to_video", "status": "running", "progress": 61}

    app = FastAPI()
    app.include_router(create_phone_jobs_router(PhoneJobDependencies(
        require_trusted_user=lambda _request: {"legacy_user_id": "user-1"},
        connect_db=lambda: conn,
        read_image_job=image_reader,
        read_video_job=video_reader,
    )))
    response = TestClient(app).get("/api/phone/v1/jobs/video-1")
    assert response.status_code == 200
    assert response.json()["job"]["progress"] == 61
    assert calls == ["video"]


def test_phone_jobs_route_never_lists_another_users_jobs() -> None:
    conn = _database()
    conn.execute(
        "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("private-1", "user-2", "text_to_image", "running", 20, None, "{}", "2026-01-01", None, None),
    )
    app = FastAPI()
    app.include_router(create_phone_jobs_router(PhoneJobDependencies(
        require_trusted_user=lambda _request: {"legacy_user_id": "user-1"},
        connect_db=lambda: conn,
        read_image_job=lambda *_args: {},
        read_video_job=lambda *_args: {},
    )))
    response = TestClient(app).get("/api/phone/v1/jobs?active=true")
    assert response.status_code == 200
    assert response.json()["items"] == []
