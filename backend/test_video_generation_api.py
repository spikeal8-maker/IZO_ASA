from __future__ import annotations

import json
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
    assert response.json()["modes"]["text_to_video"][0]["publicPricing"]["fromTokens"] > 0
    assert response.json()["modes"]["reference_to_video"] == []
    assert response.json()["availability"]["text_to_video"]["enabled"] == 1
    assert response.json()["availability"]["reference_to_video"]["reason"] == "В админке не включены модели для этого режима."
    assert response.json()["videoStorage"] == {
        "used": 0,
        "limit": 25,
        "free": 25,
        "full": False,
        "storedBytes": 0,
    }


def test_video_page_is_available_to_free_plan_and_models_define_access(video_api: TestClient):
    with main.db() as conn:
        conn.execute("UPDATE users SET role='user', plan='free' WHERE id='video-user'")

    response = video_api.get("/api/video/config")

    assert response.status_code == 200
    assert response.json()["plan"] == "free"


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
    estimate = video_api.post("/api/video/estimate", json=payload())
    response = video_api.post("/api/video/generate", json=payload())

    assert estimate.status_code == 200
    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert response.json()["tokenCost"] == estimate.json()["chargedTokens"]
    assert response.json()["tokenBalance"] == 500 - response.json()["tokenCost"]
    assert captured["aspect_ratio"] == "16:9"
    with main.db() as conn:
        row = conn.execute("SELECT status,settings_json FROM jobs WHERE id=?", (response.json()["id"],)).fetchone()
        user = conn.execute("SELECT token_balance FROM users WHERE id='video-user'").fetchone()
    assert row["status"] == "queued"
    assert "external-video-1" in row["settings_json"]
    assert user["token_balance"] == response.json()["tokenBalance"]


def test_completed_video_keeps_the_quoted_token_price(video_api: TestClient, monkeypatch):
    async def submit(**_kwargs):
        return {"id": "external-fixed-price", "status": "pending", "polling_url": "/api/v1/videos/external-fixed-price"}

    async def poll(**_kwargs):
        return {
            "id": "external-fixed-price",
            "status": "completed",
            "progress": 100,
            "unsigned_urls": ["https://video.test/result.mp4"],
            "usage": {"cost": 0.001},
        }

    async def download(_url: str, job_id: str):
        filename = f"{job_id}.mp4"
        (main.MEDIA / filename).write_bytes(b"fixed-price-video")
        return filename, len(b"fixed-price-video")

    monkeypatch.setattr(main, "submit_openrouter_video", submit)
    monkeypatch.setattr(main, "poll_openrouter_video", poll)
    monkeypatch.setattr(main, "_download_video_result", download)

    estimate = video_api.post("/api/video/estimate", json=payload()).json()["chargedTokens"]
    generated = video_api.post("/api/video/generate", json=payload())
    assert generated.status_code == 200
    assert generated.json()["tokenCost"] == estimate

    completed = video_api.get(f"/api/video/jobs/{generated.json()['id']}")
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["tokenCost"] == estimate

    with main.db() as conn:
        user = conn.execute("SELECT token_balance FROM users WHERE id='video-user'").fetchone()
        adjustments = conn.execute(
            "SELECT COUNT(*) AS c FROM token_ledger WHERE reason='openrouter_generation_adjustment'"
        ).fetchone()
        row = conn.execute("SELECT settings_json FROM jobs WHERE id=?", (generated.json()["id"],)).fetchone()
    settings = json.loads(row["settings_json"])
    assert user["token_balance"] == 500 - estimate
    assert adjustments["c"] == 0
    assert settings["openrouterBilling"]["chargedTokens"] == estimate
    assert settings["openrouterBilling"]["actualCostUsd"] == pytest.approx(0.001)


def test_completed_video_is_backfilled_into_gallery_and_can_be_deleted(video_api: TestClient):
    filename = "completed-video.mp4"
    path = main.MEDIA / filename
    path.write_bytes(b"test-video-bytes")
    settings = {
        "localFile": filename,
        "openrouterModel": MODEL["id"],
        "duration": 4,
        "resolution": "720p",
        "aspectRatio": "16:9",
        "tokenCost": 3,
    }
    with main.db() as conn:
        conn.execute(
            "INSERT INTO jobs (id,user_id,mode,provider,status,progress,prompt_original,settings_json,created_at,completed_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("video-completed", "video-user", "text_to_video", "openrouter", "completed", 100, "city in motion", json.dumps(settings), "2026-07-15T01:00:00+00:00", "2026-07-15T01:01:00+00:00"),
        )

    history = video_api.get("/api/video/history")
    assert history.status_code == 200
    assert history.json()["items"][0]["galleryVideoId"] == "gallery_video-completed"

    gallery = video_api.get("/api/gallery/items?filter=video")
    assert gallery.status_code == 200
    item = gallery.json()["items"][0]
    assert item["mediaType"] == "video"
    assert item["width"] == 1280
    assert item["height"] == 720
    assert item["videoUrl"] == "/api/video/media/video-completed"

    favorite = video_api.post(f"/api/gallery/videos/{item['id']}/favorite", json={"isFavorite": True})
    assert favorite.status_code == 200
    assert favorite.json()["favorite"] is True

    deleted = video_api.delete(f"/api/gallery/videos/{item['id']}")
    assert deleted.status_code == 200
    assert not path.exists()
    assert video_api.get("/api/gallery/items?filter=video").json()["items"] == []
    with main.db() as conn:
        job_settings = json.loads(conn.execute("SELECT settings_json FROM jobs WHERE id='video-completed'").fetchone()["settings_json"])
        pending_deletions = conn.execute("SELECT COUNT(*) AS c FROM video_file_deletions").fetchone()["c"]
    assert job_settings["galleryDeleted"] is True
    assert "localFile" not in job_settings
    assert pending_deletions == 0
