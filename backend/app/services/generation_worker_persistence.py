"""Database callbacks for the legacy worker; provider work stays outside locks."""
from __future__ import annotations

import asyncio
from contextlib import closing, nullcontext
from dataclasses import dataclass
import json
from typing import Any, Callable, MutableMapping

from . import generation_claims
from .generation_worker import OpenRouterSettlement


async def drain_owned_task(task):
    """Defer caller cancellation until owned work, including its thread, ends."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            cancelled = True
        except Exception:
            break
    if cancelled:
        task.exception()
        raise asyncio.CancelledError
    return task.result()


@dataclass(frozen=True)
class WorkerPersistence:
    connect: Callable
    refund: Callable
    finalize_billing: Callable
    reconcile_charge: Callable
    quota: Callable
    evict: Callable
    persist_image: Callable
    persist_sources: Callable
    images: MutableMapping[str, dict[str, Any]]
    optimize: Callable
    read_job: Callable
    now_iso: Callable[[], str]

    def claim_job(self, job_id: str, job: dict):
        return generation_claims.claim_job(
            self.connect, job_id, str(job.get("userId") or ""), now_iso=self.now_iso(),
        )

    def refund_tokens(self, job_id: str, reason: str) -> bool:
        with closing(self.connect()) as conn, conn:
            return self.refund(conn, job_id, reason=reason)

    def settle_openrouter(self, job_id: str, job: dict, result) -> OpenRouterSettlement:
        billing = self.finalize_billing(job.get("openrouterBilling") or {}, result.cost_usd)
        actual = int(billing.get("actualTokens") or billing.get("chargedTokens") or job.get("tokenCost") or 1)
        with closing(self.connect()) as conn, conn:
            adjustment = self.reconcile_charge(conn, job_id, actual)
        return OpenRouterSettlement(billing=billing, actual_tokens=actual, token_adjustment=adjustment)

    def gallery_quota(self, user_id: str) -> dict:
        with closing(self.connect()) as conn, conn:
            user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return self.quota(conn, user, user_id)

    def evict_gallery(self, user_id: str, quota: dict, created_at: str) -> int:
        with closing(self.connect()) as conn, conn:
            return self.evict(conn, user_id, quota, created_at)

    async def save_image(self, record: dict, job_id: str, user_id: str, request, created_at: str) -> None:
        # All nested db() calls join the fenced transaction. No thread/await here.
        self.persist_image(record, job_id)
        sources = self.persist_sources(record["id"], user_id, request, created_at)
        if sources:
            record["sources"] = sources
        self.register_transient_image(record)

    def register_transient_image(self, record: dict) -> None:
        generation_claims.after_commit(lambda: self.images.__setitem__(record["id"], record))

    async def after_completion(self, user_id: str) -> None:
        task = asyncio.create_task(asyncio.to_thread(self.optimize, user_id, limit=2), name="generation-media-optimization")
        try:
            await drain_owned_task(task)
        except Exception as error:
            print(f"generation storage optimization deferred: {type(error).__name__}")

    def refresh_job(self, job_id: str, job: dict) -> None:
        current = self.read_job(job_id, str(job.get("userId") or ""))
        # A duplicate wake can share the active owner's dictionary. Its public
        # projection omits runtime provider metadata and must not replace it.
        if current is not None and current.get("status") in generation_claims.TERMINAL:
            request = job.get("request")
            job.clear()
            job.update(current)
            if request is not None:
                job["request"] = request

    def callbacks(self) -> dict:
        names = ("claim_job", "refund_tokens", "settle_openrouter", "gallery_quota", "evict_gallery",
                 "save_image", "register_transient_image", "after_completion", "refresh_job")
        return {**{name: getattr(self, name) for name in names},
                "finalization": lambda: generation_claims.transaction(self.connect)}


async def cancel_job(job_id: str, user_id: str, *, connect, jobs, persist_job,
                     refund, read_job, interrupt, now_iso: str, admission_lock=None) -> dict:
    """Serialize terminal cancellation/refund, without interrupting a queued job."""
    async with admission_lock if admission_lock is not None else nullcontext():
        should_interrupt = False
        with closing(connect()) as conn, conn:
            with generation_claims.authorize_cancellation(conn, job_id, user_id) as row:
                if row["status"] in generation_claims.ACTIVE:
                    stored = json.loads(row["settings_json"] or "{}")
                    job = dict(jobs.get(job_id) or {})
                    job.update(id=job_id, userId=user_id, request=stored, status="cancelled",
                               progress=100, message="Отменено", completedAt=now_iso)
                    should_interrupt = row["status"] != "queued" and str(stored.get("provider") or job.get("provider")) == "comfyui"
                    refund(conn, job_id, reason="user_cancelled")
                    persist_job(job, conn=conn)
        current = read_job(job_id, user_id)
        if current is None:
            raise LookupError("GENERATION_JOB_NOT_FOUND")
        if job_id in jobs:
            jobs[job_id].update(current)
        if should_interrupt:
            await interrupt()
        return current
