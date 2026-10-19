"""Durable, uncharged admin image probe with the existing synchronous response."""

from __future__ import annotations

import asyncio
from contextlib import closing
from datetime import datetime, timezone
import json
import time
import uuid

from fastapi import HTTPException
from PIL import Image

from . import generation_claims, generation_jobs, generation_worker
from .generation_worker import GenerationClaimLost


PROBE_METADATA = {"version": 1, "kind": "openrouter_admin_test"}
IMAGE_SETTINGS = ("seed", "modelProfile", "loras", "preset", "generationTimeMs", "openrouterModel",
                  "openrouterResponseId", "openrouterUsage", "openrouterCostUsd")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _trusted_probe(host, job_id, job):
    with closing(host.db()) as conn:
        row = conn.execute("SELECT user_id,mode,provider,settings_json FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None or row["user_id"] != job.get("userId") or row["mode"] != "text_to_image" or row["provider"] != "openrouter":
        return False
    try:
        settings = json.loads(row["settings_json"] or "{}")
    except (ValueError, TypeError):
        return False
    return isinstance(settings, dict) and settings.get(generation_jobs.ADMIN_PROBE_METADATA_KEY) == PROBE_METADATA


async def process_job(host, job_id, job, request, runtime, *, started_at):
    """Dispatch trusted probes under the same local/remote claim and media fence."""
    if not job_id.startswith(generation_jobs.ADMIN_PROBE_JOB_PREFIX):
        return await generation_worker.process_generation_job(job_id, job, request, runtime, started_at=started_at)
    if not _trusted_probe(host, job_id, job):
        raise GenerationClaimLost("GENERATION_ADMIN_PROBE_MARKER_REQUIRED")
    try:
        with runtime.claim_job(job_id, job) as acquired:
            if not acquired:
                runtime.refresh_job(job_id, job)
                return False
            await _process_probe(host, job_id, job, request, runtime)
    except GenerationClaimLost:
        runtime.refresh_job(job_id, job)
    return False  # This probe has never run gallery optimization/completion hooks.


async def _process_probe(host, job_id, job, request, runtime):
    before_finalization = None
    try:
        job.update(status="running", startedAt=job.get("startedAt") or runtime.now_iso())
        runtime.persist_job(job, request)
        result = await runtime.send_to_openrouter(request, job)
        with Image.open(result.image_path) as opened:
            width, height = opened.size
        before_finalization = dict(job)
        with runtime.finalization():
            created_at, image_id = runtime.now_iso(), runtime.new_image_id()
            user_id = job["userId"]
            record = {
                "id": image_id, "userId": user_id,
                "url": runtime.public_url(result.image_path, user_id),
                "thumbnailUrl": runtime.public_url(result.thumbnail_path, user_id),
                "mode": request.mode, "provider": request.provider,
                "promptOriginal": request.prompt, "promptTranslated": request.prompt,
                "seed": request.seed, "width": width, "height": height, "modelProfile": request.modelProfile,
                "loras": [], "preset": "admin_openrouter_test", "generationTimeMs": 0,
                "isFavorite": False, "createdAt": created_at, "openrouterModel": result.model,
                "openrouterResponseId": result.response_id, "openrouterUsage": result.usage,
                "openrouterCostUsd": result.cost_usd,
            }
            host.persist_image(record, job_id)
            generation_claims.after_commit(lambda: host.images.__setitem__(image_id, record))
            job.update(status="completed", progress=100, message="OpenRouter test completed",
                       resultImageId=image_id, resultUrl=record["url"], openrouterModel=result.model,
                       openrouterResponseId=result.response_id, openrouterUsage=result.usage,
                       openrouterCostUsd=result.cost_usd, completedAt=created_at)
            runtime.persist_job(job, request)
    except GenerationClaimLost:
        raise
    except Exception:
        if before_finalization is not None:
            job.clear()
            job.update(before_finalization)
        with runtime.finalization():
            job.update(status="failed", progress=100, error=generation_jobs.PUBLIC_SERVER_ERROR,
                       message=generation_jobs.PUBLIC_SERVER_ERROR, completedAt=runtime.now_iso())
            runtime.persist_job(job, request)


def _read_result(host, job_id, user_id):
    with closing(host.db()) as conn:
        job = conn.execute("SELECT status,result_image_id FROM jobs WHERE id=? AND user_id=?", (job_id, user_id)).fetchone()
        if job is None:
            raise HTTPException(503, generation_jobs.PUBLIC_SERVER_ERROR)
        if job["status"] in {"failed", "cancelled", "expired"}:
            raise HTTPException(502, generation_jobs.PUBLIC_SERVER_ERROR)
        if job["status"] != "completed":
            return None
        image = conn.execute("SELECT * FROM images WHERE id=? AND job_id=? AND user_id=? AND deleted_at IS NULL",
                             (job["result_image_id"], job_id, user_id)).fetchone()
    if image is None:
        raise HTTPException(503, generation_jobs.PUBLIC_SERVER_ERROR)
    settings = json.loads(image["settings_json"] or "{}")
    record = {"id": image["id"], "userId": image["user_id"], "url": image["url"],
              "thumbnailUrl": image["thumbnail_url"], "mode": image["mode"], "provider": image["provider"],
              "promptOriginal": image["prompt_original"], "promptTranslated": image["prompt_translated"],
              "width": image["width"], "height": image["height"], "isFavorite": bool(image["is_favorite"]),
              "createdAt": image["created_at"], **{key: settings.get(key) for key in IMAGE_SETTINGS}}
    return {"ok": True, "image": record, "costUsd": record["openrouterCostUsd"], "model": record["openrouterModel"],
            "usage": record["openrouterUsage"], "stats": host.openrouter_usage_stats()}


async def generate(host, req, request):
    admin = host.require_trusted_admin(request)
    if "/" not in req.model:
        raise HTTPException(400, "model должен быть OpenRouter id вида provider/model")
    job_id = generation_jobs.ADMIN_PROBE_JOB_PREFIX + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    gen_req = host.GenerateRequest(mode="text_to_image", provider="openrouter", prompt=req.prompt,
                                   width=req.width, height=req.height, steps=4, modelProfile=req.model)
    job = {"id": job_id, "userId": admin["legacy_user_id"], "mode": gen_req.mode, "provider": gen_req.provider,
           "status": "queued", "progress": 0, "message": "Admin OpenRouter test", "request": gen_req.model_dump(),
           "createdAt": _now()}
    host.record_event_log("admin_openrouter_test_requested", internal_user_id=admin.get("internal_user_id"),
                          legacy_user_id=admin["legacy_user_id"], request=request,
                          properties={"jobId": job_id, "model": req.model})
    with closing(host.db()) as conn, conn:
        generation_jobs.persist_runtime_job(conn, job, request_data=gen_req.model_dump(), now_iso=_now(),
                                            admin_probe_metadata=dict(PROBE_METADATA))
    host.jobs[job_id] = job
    if host.os.environ.get("IZO_PROCESS_ROLE", "combined") != "server":
        await process_job(host, job_id, job, gen_req, host._generation_worker_runtime(), started_at=time.perf_counter())
    # In server role only the durable executor claims this row. HTTP cancellation
    # or timeout does not remove it, retry it, or charge/refund a user account.
    deadline = time.monotonic() + max(30, 2 * float(host.OPENROUTER_TIMEOUT_SECONDS) + 30)
    while True:
        result = _read_result(host, job_id, admin["legacy_user_id"])
        if result is not None:
            return result
        if time.monotonic() >= deadline:
            raise HTTPException(504, generation_jobs.PUBLIC_SERVER_ERROR)
        await asyncio.sleep(.1)
