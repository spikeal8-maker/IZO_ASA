"""Admin probe compatibility, durable execution and zero user-ledger effects."""

from __future__ import annotations

import asyncio
from contextlib import closing, nullcontext
from dataclasses import replace
import json
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest
from fastapi.testclient import TestClient

import main
from app.integrations import generation_transport
from app.services import generation_admin_probe as probe
from app.services import generation_bootstrap, generation_claims, generation_jobs, generation_leases
from app.services.generation_worker import GenerationClaimLost


ORIGIN = {"Origin": "https://izo.alikinas.ru"}
REQUEST = {"model": "fixture/admin-image", "prompt": "Owned admin probe", "width": 512, "height": 768}


def _session(user_id, role):
    with main.db() as conn:
        conn.execute("INSERT INTO users (id,internal_user_id,role,token_balance,created_at,last_login_at) VALUES (?,?,?,73,?,?)",
                     (user_id, "internal-" + user_id, role, "2026-10-18T00:00:00+00:00", "2026-10-18T00:00:00+00:00"))
    return main.create_auth_session("internal-" + user_id, user_id, provider="web_email", platform="web_desktop")["session_token"]


@pytest.fixture
def fixture(monkeypatch):
    monkeypatch.setenv("IZO_PROCESS_ROLE", "combined")
    monkeypatch.setattr(main, "jobs", {})
    monkeypatch.setattr(main, "images", {})
    main.init_db()
    return {"admin": _session("probe-admin", "admin"), "other": _session("probe-other", "user")}


def _financial():
    with main.db() as conn:
        user = conn.execute("SELECT token_balance,tokens_used,generation_count FROM users WHERE id='probe-admin'").fetchone()
        return tuple(user), conn.execute("SELECT COUNT(*) FROM token_ledger").fetchone()[0]


def _rows():
    with main.db() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM jobs ORDER BY created_at,id")]


def _provider(monkeypatch):
    calls = []
    async def fake(request, job):
        generation_bootstrap.require_executor(main.os.environ)
        calls.append(job["id"])
        # Exercise the same intermediate persistence that formerly discarded
        # trusted probe identity before the final result was available.
        job.update(status="sent_to_openrouter", progress=24)
        main.persist_job(job, request)
        path, thumbnail = main.MEDIA / (job["id"] + ".png"), main.MEDIA / (job["id"] + ".webp")
        with Image.new("RGB", (640, 480), "green") as image:
            image.save(path)
            image.resize((64, 48)).save(thumbnail)
        return SimpleNamespace(image_path=path, thumbnail_path=thumbnail, model=request.modelProfile,
                               response_id="fixture-response", usage={"images": 1}, cost_usd=.014)
    monkeypatch.setattr(main, "send_to_openrouter", fake)
    return calls, fake


def _assert_success(payload):
    assert set(payload) == {"ok", "image", "costUsd", "model", "usage", "stats"}
    assert payload["ok"] is True and payload["costUsd"] == .014
    assert payload["model"] == REQUEST["model"] and payload["usage"] == {"images": 1}
    assert payload["stats"]["pricedImages"] == 1
    image = payload["image"]
    assert set(image) == {"id", "userId", "url", "thumbnailUrl", "mode", "provider", "promptOriginal",
        "promptTranslated", "seed", "width", "height", "modelProfile", "loras", "preset", "generationTimeMs",
        "isFavorite", "createdAt", "openrouterModel", "openrouterResponseId", "openrouterUsage", "openrouterCostUsd"}
    assert image["preset"] == "admin_openrouter_test" and image["generationTimeMs"] == 0
    assert image["modelProfile"] == REQUEST["model"] and image["userId"] == "probe-admin"
    assert (image["width"], image["height"]) == (640, 480)
    assert image["promptOriginal"] == image["promptTranslated"] == REQUEST["prompt"]


async def _wait_for_row():
    async def wait():
        while True:
            rows = _rows()
            if rows:
                assert len(rows) == 1
                return rows[0]
            await asyncio.sleep(.001)
    return await asyncio.wait_for(wait(), 3)


async def _execute_claim():
    grant = generation_leases.claim_next(main.db, "a" * 32)
    assert grant is not None
    claim, job = grant
    main.jobs[claim.job_id] = job
    request = main.GenerateRequest(**job["request"])
    runtime = replace(main._generation_worker_runtime(), claim_job=lambda *_: nullcontext(True), after_completion=None)
    transport = httpx.MockTransport(lambda request: (_ for _ in ()).throw(AssertionError("unexpected HTTP")))
    with generation_claims.bind_claim(claim), generation_transport.bind(transport):
        assert await probe.process_job(main, claim.job_id, job, request, runtime, started_at=0) is False
    return job


def test_combined_admin_probe_keeps_exact_response_preset_cost_and_no_user_charge(fixture, monkeypatch):
    before = _financial()
    calls, _ = _provider(monkeypatch)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Admin probe must not use ordinary billing/quota/completion callbacks")
    for name in ("charge_generation_tokens", "reconcile_openrouter_token_charge", "refund_generation_tokens",
                 "gallery_quota_for_user", "evict_gallery_images_for_new_save", "optimize_gallery_storage_for_user",
                 "persist_image_sources"):
        monkeypatch.setattr(main, name, forbidden)
    with closing(TestClient(main.app)) as client:
        client.cookies.set(main.TRUSTED_SESSION_COOKIE_NAME, fixture["admin"])
        response = client.post("/api/admin/openrouter/test-generate", json=REQUEST, headers=ORIGIN)
        assert response.status_code == 200
        _assert_success(response.json())
        row = _rows()[0]
        assert calls == [row["id"]] and row["status"] == "completed"
        assert json.loads(row["settings_json"])[generation_jobs.ADMIN_PROBE_METADATA_KEY] == probe.PROBE_METADATA
        assert _financial() == before
        main.jobs.clear()
        main.images.clear()
        assert probe._read_result(main, row["id"], "probe-admin") == response.json()
        public = client.get("/api/jobs/" + row["id"])
        assert public.status_code == 200 and generation_jobs.ADMIN_PROBE_METADATA_KEY not in public.text
        restored = {"id": row["id"], "userId": "probe-admin", "request": json.loads(row["settings_json"])}
        parsed = main.GenerateRequest(**restored["request"])
        assert asyncio.run(probe.process_job(main, row["id"], restored, parsed,
                                            main._generation_worker_runtime(), started_at=0)) is False
        assert calls == [row["id"]] and restored["status"] == "completed" and _financial() == before


def test_server_admin_probe_waits_for_durable_claim_and_returns_same_synchronous_result(fixture, monkeypatch):
    monkeypatch.setenv("IZO_PROCESS_ROLE", "server")
    before = _financial()
    calls, _ = _provider(monkeypatch)
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://testserver",
                                     cookies={main.TRUSTED_SESSION_COOKIE_NAME: fixture["admin"]}) as client:
            pending = asyncio.create_task(client.post("/api/admin/openrouter/test-generate", json=REQUEST, headers=ORIGIN))
            row = await _wait_for_row()
            try:
                assert row["status"] == "queued" and not pending.done() and calls == []
                assert json.loads(row["settings_json"])[generation_jobs.ADMIN_PROBE_METADATA_KEY] == probe.PROBE_METADATA
                main.jobs.clear()
                completed = await _execute_claim()
                assert completed["status"] == "completed"
                response = await asyncio.wait_for(pending, 3)
                assert response.status_code == 200
                _assert_success(response.json())
            finally:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            assert generation_leases.claim_next(main.db, "b" * 32) is None
    asyncio.run(exercise())
    assert len(calls) == 1 and _financial() == before


def test_abandoned_http_wait_keeps_probe_durable_without_running_it_on_server(fixture, monkeypatch):
    monkeypatch.setenv("IZO_PROCESS_ROLE", "server")
    before = _financial()
    calls, _ = _provider(monkeypatch)
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://testserver",
                                     cookies={main.TRUSTED_SESSION_COOKIE_NAME: fixture["admin"]}) as client:
            pending = asyncio.create_task(client.post("/api/admin/openrouter/test-generate", json=REQUEST, headers=ORIGIN))
            row = await _wait_for_row()
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            assert calls == [] and _rows()[0]["status"] == "queued"
            main.jobs.clear()
            await _execute_claim()
            _assert_success(probe._read_result(main, row["id"], "probe-admin"))
    asyncio.run(exercise())
    assert len(calls) == 1 and _financial() == before


@pytest.mark.parametrize("failure", ["provider", "terminal-write"])
def test_failure_cannot_leave_a_success_image_or_change_user_finances(fixture, monkeypatch, failure):
    before = _financial()
    calls, _ = _provider(monkeypatch)
    if failure == "provider":
        async def failed(_request, job):
            calls.append(job["id"])
            raise RuntimeError("private provider endpoint and secret configuration")
        monkeypatch.setattr(main, "send_to_openrouter", failed)
    else:
        persist = main.persist_job
        def reject_terminal(job, request=None, conn=None):
            if job["status"] == "completed":
                raise RuntimeError("private database path")
            persist(job, request, conn)
        monkeypatch.setattr(main, "persist_job", reject_terminal)
    with closing(TestClient(main.app)) as client:
        client.cookies.set(main.TRUSTED_SESSION_COOKIE_NAME, fixture["admin"])
        response = client.post("/api/admin/openrouter/test-generate", json=REQUEST, headers=ORIGIN)
    assert response.status_code == 502 and "private" not in response.text
    assert _rows()[0]["status"] == "failed" and len(calls) == 1
    with main.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 0
    assert main.images == {} and _financial() == before


def test_cancelled_probe_rejects_a_late_worker_result_without_any_financial_effect(fixture, monkeypatch):
    monkeypatch.setenv("IZO_PROCESS_ROLE", "server")
    before = _financial()
    calls, fake = _provider(monkeypatch)
    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()
        async def held(request, job):
            result = await fake(request, job)
            entered.set()
            await release.wait()
            return result
        monkeypatch.setattr(main, "send_to_openrouter", held)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://testserver",
                                     cookies={main.TRUSTED_SESSION_COOKIE_NAME: fixture["admin"]}) as client:
            pending = asyncio.create_task(client.post("/api/admin/openrouter/test-generate", json=REQUEST, headers=ORIGIN))
            row = await _wait_for_row()
            worker = asyncio.create_task(_execute_claim())
            try:
                await asyncio.wait_for(entered.wait(), 3)
                cancelled = await client.post("/api/jobs/" + row["id"] + "/cancel", headers=ORIGIN)
                assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
                release.set()
                assert (await asyncio.wait_for(worker, 3))["status"] == "cancelled"
                assert (await asyncio.wait_for(pending, 3)).status_code == 502
            finally:
                release.set()
                pending.cancel()
                worker.cancel()
                await asyncio.gather(pending, worker, return_exceptions=True)
    asyncio.run(exercise())
    assert len(calls) == 1 and _rows()[0]["status"] == "cancelled" and _financial() == before
    with main.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 0
    assert main.images == {}


def test_untrusted_request_cannot_create_a_free_probe_marker_or_execute_one(fixture, monkeypatch):
    calls, _ = _provider(monkeypatch)
    request = main.GenerateRequest(**{**REQUEST, "provider": "openrouter", "mode": "text_to_image"})
    job = {"id": "admin_or_test_spoof", "userId": "probe-other", "mode": request.mode,
           "provider": request.provider, "status": "queued", "request": request.model_dump()}
    with main.db() as conn:
        generation_jobs.persist_runtime_job(conn, job,
            request_data={**request.model_dump(), generation_jobs.ADMIN_PROBE_METADATA_KEY: probe.PROBE_METADATA},
            now_iso="2026-10-18T00:00:00+00:00")
    assert generation_jobs.ADMIN_PROBE_METADATA_KEY not in json.loads(_rows()[0]["settings_json"])
    with pytest.raises(GenerationClaimLost, match="GENERATION_ADMIN_PROBE_MARKER_REQUIRED"):
        asyncio.run(probe.process_job(main, job["id"], job, request, main._generation_worker_runtime(), started_at=0))
    assert calls == [] and _rows()[0]["status"] == "queued"


def test_guest_and_nonadmin_cannot_enqueue_and_invalid_model_has_no_effect(fixture, monkeypatch):
    calls, _ = _provider(monkeypatch)
    before = _financial()
    with closing(TestClient(main.app)) as client:
        guest = client.post("/api/admin/openrouter/test-generate", json=REQUEST, headers={**ORIGIN, "X-OneNode-User": "probe-admin"})
        assert guest.status_code == 401
        client.cookies.set(main.TRUSTED_SESSION_COOKIE_NAME, fixture["other"])
        assert client.post("/api/admin/openrouter/test-generate", json=REQUEST, headers=ORIGIN).status_code == 403
        client.cookies.set(main.TRUSTED_SESSION_COOKIE_NAME, fixture["admin"])
        assert client.post("/api/admin/openrouter/test-generate", json={**REQUEST, "model": "invalid"}, headers=ORIGIN).status_code == 400
    assert calls == [] and _rows() == [] and _financial() == before
