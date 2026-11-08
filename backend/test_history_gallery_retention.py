"""A new authorized completion must not evict or recompress restored history."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import main
from app.services.history_replay import HistoryReplayConfigurationError, seal_restored_history
from app.storage.gallery_repository import select_gallery_eviction_candidates

OWNER = "historical-owner"


class RecordingQueue:
    def __init__(self):
        self.items = []

    async def put(self, job_id):
        self.items.append(job_id)

    def qsize(self):
        return len(self.items)


def add_image(conn, image_id, owner, index, *, archived=False, deleted=False, favorite=False):
    extension = "webp" if archived else "png"
    path = main.MEDIA / f"{image_id}.{extension}"
    with Image.effect_noise((128, 96), 80).convert("RGB") as picture:
        picture.save(path, "WEBP" if archived else "PNG")
    thumb = main.create_thumbnail(path)
    created = f"2020-01-01T00:00:{index:02d}+00:00"
    conn.execute(
        "INSERT INTO jobs (id,user_id,mode,provider,status,progress,settings_json,created_at) "
        "VALUES (?,?,'text_to_image','comfyui','completed',100,'{}',?)",
        ("job-" + image_id, owner, created),
    )
    conn.execute(
        "INSERT INTO images (id,user_id,job_id,url,thumbnail_url,width,height,mode,provider,"
        "settings_json,created_at,storage_tier,deleted_at,is_favorite,original_bytes,stored_bytes) "
        "VALUES (?,?,?,?,?,128,96,'text_to_image','comfyui','{}',?,?,?,?,?,?)",
        (image_id, owner, "job-" + image_id, main.public_url(path, owner),
         main.public_url(thumb, owner), created, "optimized" if archived else "original",
         "2021-01-01" if deleted else None, int(favorite), path.stat().st_size, path.stat().st_size),
    )


def frozen_rows():
    with closing(main.db()) as conn:
        return {
            table: [tuple(row) for row in conn.execute(
                f"SELECT * FROM {table} WHERE id IN "
                "(SELECT resource_id FROM history_replay_resources WHERE resource=?) ORDER BY id",
                (table,),
            )]
            for table in ("images", "jobs", "token_ledger")
        }


def assert_history_unchanged(state):
    assert frozen_rows() == state.rows
    for path, digest in state.media.items():
        assert path.is_file(), f"Historical file was removed: {path.name}"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, path.name


@pytest.fixture
def historical_gallery(tmp_path, monkeypatch):
    monkeypatch.delenv("IZO_PREPROD_PRESERVE_HISTORY", raising=False)
    monkeypatch.delenv("IZO_HISTORY_SNAPSHOT_ID", raising=False)
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "retention.sqlite3")
    monkeypatch.setattr(main, "MEDIA", tmp_path / "media")
    main.MEDIA.mkdir()
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    monkeypatch.setattr(main, "queue", RecordingQueue())
    monkeypatch.setattr(main, "rate_limits", {"hourly": 0, "daily": 0})
    monkeypatch.setattr(main, "GALLERY_ARCHIVE_MAX_SIDE", 96)
    main.jobs.clear()
    main.images.clear()
    main.init_db()
    config = copy.deepcopy(main.get_tariff_config())
    config["mini"]["gallery_slots"] = 1
    monkeypatch.setattr(main, "get_tariff_config", lambda conn=None: copy.deepcopy(config))
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with closing(main.db()) as conn, conn:
        for owner in (OWNER, "foreign-owner"):
            conn.execute(
                "INSERT INTO users (id,internal_user_id,role,plan,token_balance,daily_tokens_used,"
                "last_daily_reset,created_at,last_login_at,plan_expires_at) "
                "VALUES (?,?,'user','mini',100,5000,?,'2020-01-01','2020-01-01','2099-01-01')",
                (owner, "internal-" + owner, today),
            )
        for index in range(12):
            add_image(conn, f"old-{index:02d}", OWNER, index,
                      archived=index < 2, favorite=index == 11)
        add_image(conn, "foreign-image", "foreign-owner", 20)
        add_image(conn, "old-deleted", OWNER, 21, deleted=True)
        conn.execute(
            "INSERT INTO token_ledger (id,user_id,delta,reason,created_at) "
            "VALUES ('old-ledger',?,100,'historical','2020-01-01')", (OWNER,),
        )
    token = main.create_auth_session(
        "internal-" + OWNER, OWNER, provider="web_email", platform="web_desktop",
    )["session_token"]
    with closing(main.db()) as conn, conn:
        seal_restored_history(conn, snapshot_id="retention-regression")
    monkeypatch.setenv("IZO_PREPROD_PRESERVE_HISTORY", "1")
    monkeypatch.setenv("IZO_HISTORY_SNAPSHOT_ID", "retention-regression")
    state = SimpleNamespace(
        token=token, config=config, provider_calls=[],
        rows=frozen_rows(),
        media={path: hashlib.sha256(path.read_bytes()).hexdigest()
               for path in main.MEDIA.rglob("*") if path.is_file()},
    )

    async def fake_provider(request, job):
        state.provider_calls.append(job["id"])
        path = main.MEDIA / f"{job['id']}.png"
        with Image.new("RGB", (request.width, request.height), "navy") as picture:
            picture.save(path)
        return SimpleNamespace(
            prompt_id="synthetic-" + job["id"], image_path=path,
            thumbnail_path=main.create_thumbnail(path), history={"outputs": {}},
        )

    monkeypatch.setattr(main, "send_to_comfyui", fake_provider)
    yield state
    main.jobs.clear()
    main.images.clear()


def submit(client, state, key):
    return client.post(
        "/api/generate",
        headers={"Authorization": "Bearer " + state.token, "Idempotency-Key": key},
        json={"provider": "comfyui", "mode": "text_to_image", "prompt": "retention regression",
              "seed": 42, "width": 704, "height": 704},
    )


def complete(job_id):
    async def no_delay(_seconds):
        return None

    job = main.jobs[job_id]
    runtime = replace(main._generation_worker_runtime(), sleep=no_delay)
    asyncio.run(main.generation_worker.process_generation_job(
        job_id, job, main.GenerateRequest(**job["request"]), runtime,
        started_at=time.perf_counter(),
    ))
    assert job["status"] == "completed", job.get("error")
    assert job["gallerySaveStatus"] == "saved"
    return job["resultImageId"]


def test_new_http_completion_preserves_history_and_only_evicts_new_work(historical_gallery):
    state = historical_gallery
    with closing(TestClient(main.app)) as client:
        response = submit(client, state, "new-operation-one")
        assert response.status_code == 200, response.text
        first_job = response.json()["id"]
        first_image = complete(first_job)
        assert_history_unchanged(state)
        with closing(main.db()) as conn:
            first_url = conn.execute("SELECT url FROM images WHERE id=?", (first_image,)).fetchone()[0]
            assert conn.execute("SELECT COUNT(*) FROM token_ledger WHERE user_id=?", (OWNER,)).fetchone()[0] == 2
            assert conn.execute("SELECT token_balance FROM users WHERE id=?", (OWNER,)).fetchone()[0] == 99
        first_path = main.local_media_path_from_url(first_url)
        assert first_path is not None and first_path.is_file()
        replay = submit(client, state, "new-operation-one")
        assert replay.status_code == 200 and replay.json()["id"] == first_job
        assert replay.json()["status"] == "completed"
        assert replay.json()["resultImageId"] == first_image
        assert state.provider_calls == [first_job]
        assert main._worker_gallery_quota(OWNER)["gallery_slots"] == 13
        second = submit(client, state, "new-operation-two")
        assert second.status_code == 200, second.text
        second_job = second.json()["id"]
        second_image = complete(second_job)
        assert first_image != second_image
        assert_history_unchanged(state)
        with closing(main.db()) as conn:
            assert conn.execute("SELECT deleted_at FROM images WHERE id=?", (first_image,)).fetchone()[0]
            assert conn.execute("SELECT deleted_at FROM images WHERE id=?", (second_image,)).fetchone()[0] is None
            assert conn.execute("SELECT COUNT(*) FROM generation_admissions WHERE user_id=?", (OWNER,)).fetchone()[0] == 2
            assert conn.execute("SELECT COUNT(*) FROM token_ledger WHERE user_id=?", (OWNER,)).fetchone()[0] == 3
            assert conn.execute("SELECT token_balance FROM users WHERE id=?", (OWNER,)).fetchone()[0] == 98
        assert not first_path.exists()
        assert state.provider_calls == [first_job, second_job]
        assert main.queue.items == [first_job, second_job]
    main.load_db_state()
    assert_history_unchanged(state)


@pytest.mark.parametrize("repeat", range(3))
def test_direct_concurrent_compaction_only_claims_new_image_once(historical_gallery, repeat):
    state = historical_gallery
    with closing(main.db()) as conn, conn:
        add_image(conn, "new-storage", OWNER, 30)
    gate = threading.Barrier(2)

    def optimize(_):
        gate.wait(timeout=10)
        return main.optimize_gallery_storage_for_user(OWNER, keep_recent=0, limit=1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(optimize, range(2)))
    assert sum(result["optimized"] for result in results) == 1
    assert sum(result["errors"] for result in results) == 0
    assert_history_unchanged(state)
    with closing(main.db()) as conn:
        row = conn.execute("SELECT url,storage_tier FROM images WHERE id='new-storage'").fetchone()
        assert row["storage_tier"] == "optimized"
        assert main.local_media_path_from_url(row["url"]).is_file()
    assert main.optimize_gallery_storage_for_user(OWNER, keep_recent=0)["checked"] == 0


def test_stale_eviction_candidates_cannot_reach_row_or_file_deletion(historical_gallery, monkeypatch):
    with closing(main.db()) as conn:
        stale = conn.execute("SELECT id,url,thumbnail_url FROM images WHERE id='old-00'").fetchone()
    monkeypatch.setattr(main, "storage_select_gallery_eviction_candidates", lambda *a, **k: [stale])
    with closing(main.db()) as conn, conn:
        removed = main.evict_gallery_images_for_new_save(
            conn, OWNER, {"gallery_slots": 1, "gallery_used": 2}, datetime.now(timezone.utc).isoformat(),
        )
    assert removed == 0
    assert_history_unchanged(historical_gallery)


@pytest.mark.parametrize("operation", ["quota", "selection", "eviction", "optimization"])
def test_invalid_history_boundary_fails_before_automatic_mutation(historical_gallery, monkeypatch, operation):
    monkeypatch.setenv("IZO_HISTORY_SNAPSHOT_ID", "wrong-snapshot")
    with pytest.raises(HistoryReplayConfigurationError):
        with closing(main.db()) as conn, conn:
            if operation == "quota":
                main._worker_gallery_quota(OWNER)
            elif operation == "selection":
                select_gallery_eviction_candidates(conn, OWNER, limit=1)
            elif operation == "eviction":
                main.evict_gallery_images_for_new_save(
                    conn, OWNER, {"gallery_slots": 1, "gallery_used": 2}, "2026-11-08",
                )
            else:
                main.optimize_gallery_storage_for_user(OWNER, keep_recent=0)
    assert_history_unchanged(historical_gallery)


def test_disabled_preservation_keeps_ordinary_quota_and_oldest_candidate_order(historical_gallery, monkeypatch):
    monkeypatch.setenv("IZO_PREPROD_PRESERVE_HISTORY", "0")
    quota = main._worker_gallery_quota(OWNER)
    assert quota["gallery_slots"] == 1 and quota["gallery_used"] == 12
    with closing(main.db()) as conn:
        rows = select_gallery_eviction_candidates(conn, OWNER, limit=2)
    assert [row["id"] for row in rows] == ["old-00", "old-01"]
    assert_history_unchanged(historical_gallery)


def test_zero_slots_do_not_gain_a_new_work_allowance(historical_gallery):
    historical_gallery.config["mini"]["gallery_slots"] = 0
    quota = main._worker_gallery_quota(OWNER)
    assert quota["gallery_slots"] == 0 and quota["gallery_full"] is True
    assert main.gallery_policy.gallery_eviction_target(quota) == 0
    assert_history_unchanged(historical_gallery)
