from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main


MODEL = {
    "id": "video/test",
    "name": "Test Video",
    "description": "test",
    "modes": ["text_to_video", "image_to_video", "first_last_frame"],
    "supportedResolutions": ["720p"],
    "supportedAspectRatios": ["16:9", "9:16"],
    "supportedSizes": ["1280x720", "720x1280"],
    "supportedDurations": [4, 6],
    "supportedFrameImages": ["first_frame", "last_frame"],
    "generateAudio": True,
    "pricingSkus": {"duration_seconds_720p": 0.1},
}


@pytest.fixture
def video_api(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "video.sqlite3")
    monkeypatch.setattr(main, "MEDIA", tmp_path / "media")
    main.MEDIA.mkdir()
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    monkeypatch.setattr(main, "worker_started", True)
    main.init_db()
    now = "2026-07-15T00:00:00+00:00"
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id,internal_user_id,language,role,plan,token_balance,created_at,last_login_at) VALUES (?,?,?,?,?,?,?,?)",
            ("video-user", "video-internal", "ru", "admin", "business", 500, now, now),
        )
        conn.execute(
            "INSERT INTO auth_identities (id,internal_user_id,legacy_user_id,provider,provider_user_id,linked_at) VALUES (?,?,?,?,?,?)",
            ("video-identity", "video-internal", "video-user", "web_email", "video@test.local", now),
        )
    session = main.create_auth_session("video-internal", "video-user", provider="web_email", platform="web_desktop")

    async def catalog(force: bool = False):
        del force
        return [MODEL]

    async def exchange():
        return {"rate": 80.0, "source": "test"}

    monkeypatch.setattr(main, "fetch_openrouter_video_catalog", catalog)
    monkeypatch.setattr(main, "fetch_usd_rub_rate", exchange)
    monkeypatch.setattr(main, "openrouter_headers", lambda: {"Authorization": "Bearer test"})
    monkeypatch.setattr(main, "_saved_setting", lambda key: {"enabled": {"text_to_video": [MODEL["id"]], "image_to_video": [MODEL["id"]], "first_last_frame": [MODEL["id"]]}} if key == "openrouter_video_models" else {})
    client = TestClient(main.app)
    client.cookies.set("onenode_session", session["session_token"])
    return client


def payload(**updates):
    base = {
        "mode": "text_to_video", "model": MODEL["id"], "prompt": "camera moves slowly",
        "duration": 4, "resolution": "720p", "aspectRatio": "16:9", "generateAudio": False,
    }
    return {**base, **updates}


def test_video_config_returns_only_enabled_catalog_models(video_api: TestClient):
    response = video_api.get("/api/video/config")
    assert response.status_code == 200
    assert response.json()["modes"]["text_to_video"][0]["id"] == MODEL["id"]
    assert response.json()["modes"]["reference_to_video"] == []


def test_video_estimate_rejects_unsupported_resolution(video_api: TestClient):
    response = video_api.post("/api/video/estimate", json=payload(resolution="1080p"))
    assert response.status_code == 422
    generated = video_api.post("/api/video/generate", json=payload(resolution="1080p"))
    assert generated.status_code == 422
    assert "разрешение" in generated.json()["detail"].lower()


def test_video_generate_persists_external_job_and_server_price(video_api: TestClient, monkeypatch):
    captured = {}

    async def submit(**kwargs):
        captured.update(kwargs["payload"])
        return {"id": "external-video-1", "status": "pending", "polling_url": "/api/v1/videos/external-video-1"}

    monkeypatch.setattr(main, "submit_openrouter_video", submit)
    response = video_api.post("/api/video/generate", json=payload())

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert response.json()["tokenCost"] > 0
    assert captured["aspect_ratio"] == "16:9"
    with main.db() as conn:
        row = conn.execute("SELECT status,settings_json FROM jobs WHERE id=?", (response.json()["id"],)).fetchone()
    assert row["status"] == "queued"
    assert "external-video-1" in row["settings_json"]
