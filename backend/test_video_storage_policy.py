from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

import main
import video_storage_audit
from app.services import video_storage


NOW = "2026-07-17T00:00:00+00:00"


def _make_user(*, user_id: str = "video-policy-user", plan: str = "mini") -> None:
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id,internal_user_id,language,role,plan,token_balance,created_at,last_login_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (user_id, f"internal-{user_id}", "ru", "user", plan, 100, NOW, NOW),
        )


def _make_video(index: int, *, user_id: str = "video-policy-user", favorite: bool = False) -> tuple[str, str]:
    job_id = f"video-job-{index}"
    video_id = f"gallery-video-{index}"
    filename = f"{job_id}.mp4"
    created_at = f"2026-07-17T00:{index:02d}:00+00:00"
    settings = {"localFile": filename, "galleryVideoId": video_id, "duration": 4, "aspectRatio": "16:9"}
    (main.MEDIA / filename).write_bytes(b"0000ftypisom0000test-video")
    with main.db() as conn:
        conn.execute(
            "INSERT INTO jobs (id,user_id,mode,provider,status,progress,prompt_original,settings_json,created_at,completed_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (job_id, user_id, "text_to_video", "openrouter", "completed", 100, "test", json.dumps(settings), created_at, created_at),
        )
        conn.execute(
            "INSERT INTO videos (id,user_id,job_id,url,width,height,duration_seconds,aspect_ratio,mode,provider,"
            "prompt_original,settings_json,stored_bytes,is_favorite,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                video_id, user_id, job_id, f"/api/video/media/{job_id}", 1280, 720, 4, "16:9",
                "text_to_video", "openrouter", "test", json.dumps(settings),
                (main.MEDIA / filename).stat().st_size, 1 if favorite else 0, created_at,
            ),
        )
    return video_id, filename


def test_video_storage_tariff_migration_is_exact_and_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "video-tariffs.sqlite3")
    main.init_db()
    with main.db() as conn:
        tariffs = main.get_tariff_config(conn)
        assert [tariffs[plan]["video_slots"] for plan in main.PLAN_ORDER] == [0, 1, 5, 10, 25]
        assert conn.execute("SELECT 1 FROM admin_settings WHERE key='tariffs'").fetchone() is None
        tariffs["business"]["video_slots"] = 17
        conn.execute(
            "INSERT INTO admin_settings (key, value_json, updated_at) VALUES ('tariffs', ?, ?)",
            (json.dumps(tariffs, ensure_ascii=False), NOW),
        )
        assert main.migrate_video_storage_tariffs(conn, now=datetime.now(timezone.utc).isoformat()) is False
        assert main.get_tariff_config(conn)["business"]["video_slots"] == 17


def test_over_limit_account_evicts_two_oldest_unprotected_videos() -> None:
    main.init_db()
    _make_user()
    first, first_file = _make_video(1)
    second, second_file = _make_video(2)
    third, third_file = _make_video(3)

    with main.db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id='video-policy-user'").fetchone()
        conn.execute("BEGIN IMMEDIATE")
        assert main._evict_videos_for_new_result(conn, user, "video-policy-user", now=NOW) == 2

    with main.db() as conn:
        active = [row["id"] for row in conn.execute("SELECT id FROM videos WHERE deleted_at IS NULL ORDER BY created_at")]
        queued = [row["filename"] for row in conn.execute("SELECT filename FROM video_file_deletions ORDER BY created_at,id")]
        assert active == [third]
        assert set(queued) == {first_file, second_file}
        for job_id in ("video-job-1", "video-job-2"):
            settings = json.loads(conn.execute("SELECT settings_json FROM jobs WHERE id=?", (job_id,)).fetchone()["settings_json"])
            assert settings["galleryDeleted"] is True
            assert "localFile" not in settings
    assert first != second
    assert third_file not in (first_file, second_file)


def test_favorite_video_blocks_reservation_when_all_slots_are_protected() -> None:
    main.init_db()
    _make_user()
    _make_video(1, favorite=True)
    with main.db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id='video-policy-user'").fetchone()
        with pytest.raises(HTTPException) as exc:
            main._video_storage_reservation(conn, user, "video-policy-user")
    assert exc.value.status_code == 409


def test_storage_state_counts_pending_jobs_as_reserved() -> None:
    main.init_db()
    _make_user(plan="plus")
    _make_video(1, favorite=True)
    with main.db() as conn:
        conn.execute(
            "INSERT INTO jobs (id,user_id,mode,provider,status,progress,prompt_original,settings_json,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("video-pending", "video-policy-user", "text_to_video", "openrouter", "queued", 10, "pending", "{}", NOW),
        )
        state = video_storage.storage_state(conn, "video-policy-user", limit=5)
    assert (state.active, state.favorite, state.reserved, state.protected) == (1, 1, 1, 2)
    assert state.can_reserve is True


def test_finalization_claim_is_single_owner_and_recovers_stale_claim() -> None:
    main.init_db()
    _make_user()
    with main.db() as conn:
        conn.execute(
            "INSERT INTO jobs (id,user_id,mode,provider,status,progress,prompt_original,settings_json,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("video-finalize", "video-policy-user", "text_to_video", "openrouter", "queued", 10, "pending", "{}", NOW),
        )

    claimed, row = main._claim_video_finalization("video-finalize")
    assert claimed is True
    assert row["status"] == "finalizing"
    claimed_again, _ = main._claim_video_finalization("video-finalize")
    assert claimed_again is False

    with main.db() as conn:
        settings = json.loads(conn.execute("SELECT settings_json FROM jobs WHERE id='video-finalize'").fetchone()["settings_json"])
        settings["finalizingAt"] = "2020-01-01T00:00:00+00:00"
        conn.execute("UPDATE jobs SET settings_json=? WHERE id='video-finalize'", (json.dumps(settings),))
    reclaimed, _ = main._claim_video_finalization("video-finalize")
    assert reclaimed is True


def test_video_download_streams_to_atomic_file_and_rejects_invalid_payload(monkeypatch) -> None:
    main.init_db()

    class FakeResponse:
        def __init__(self, payload: bytes):
            self.payload = payload
            self.headers = {"content-length": str(len(payload))}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        async def aiter_bytes(self, _chunk_size: int):
            yield self.payload[:9]
            yield self.payload[9:]

    class FakeClient:
        payload = b""

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def stream(self, *_args, **_kwargs):
            return FakeResponse(self.payload)

    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    FakeClient.payload = b"0000ftypisom0000streamed-video"
    filename, stored_bytes = asyncio.run(main._download_video_result("https://provider/video", "video-stream"))
    assert filename == "video-stream.mp4"
    assert stored_bytes == len(FakeClient.payload)
    assert (main.MEDIA / filename).read_bytes() == FakeClient.payload
    assert not (main.MEDIA / f"{filename}.part").exists()

    FakeClient.payload = b"not-an-mp4-payload-with-enough-bytes"
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main._download_video_result("https://provider/invalid", "video-invalid"))
    assert exc.value.status_code == 502
    assert not (main.MEDIA / "video-invalid.mp4").exists()
    assert not (main.MEDIA / "video-invalid.mp4.part").exists()


def test_video_storage_audit_reports_missing_and_over_limit_separately() -> None:
    main.init_db()
    _make_user()
    _make_video(1, favorite=True)
    _, missing_filename = _make_video(2)
    (main.MEDIA / missing_filename).unlink()

    report = video_storage_audit.audit_video_storage(item_limit=10)

    assert report["missing_files"][0]["file"] == missing_filename
    assert "missing_files" in report["issues"]
    assert report["over_limit_users"][0]["active"] == 2
    assert report["warnings"] == ["over_limit_users_shrink_on_next_successful_generation"]
