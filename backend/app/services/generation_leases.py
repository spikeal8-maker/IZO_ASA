"""Single-writer durable scheduling for the separate generation executor.

Only the API process uses this module. A lease is persisted before the worker
receives any provider command. Expiry never requeues an uncertain operation.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
import math
import re
import time
import uuid

from . import generation_claims, generation_jobs
from .generation_worker import GenerationClaimLost
from ..security.trial_access import settle_trial_generation


IMAGE_MODES = ("text_to_image", "image_to_image", "edit", "paint", "inpaint", "outpaint",
               "faceswap", "remove_background", "try_on", "texture_transfer")
IMAGE_SQL = "provider IN ('comfyui','openrouter') AND mode IN (" + ",".join("?" for _ in IMAGE_MODES) + ")"
LEASE_SECONDS = 30.0
WORKER_ID = re.compile(r"[a-f0-9]{32}\Z")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _settings(row) -> dict:
    try:
        value = json.loads(row["settings_json"] or "{}")
    except (TypeError, ValueError):
        raise GenerationClaimLost("GENERATION_DURABLE_REQUEST_INVALID") from None
    if not isinstance(value, dict):
        raise GenerationClaimLost("GENERATION_DURABLE_REQUEST_INVALID")
    return value


def claim_next(connect, worker_id: str, *, lease_seconds=LEASE_SECONDS):
    if not isinstance(worker_id, str) or WORKER_ID.fullmatch(worker_id) is None:
        raise ValueError("GENERATION_WORKER_ID_INVALID")
    if not 1 <= lease_seconds <= 300:
        raise ValueError("GENERATION_LEASE_DURATION_INVALID")
    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        active = conn.execute(
            "SELECT id FROM jobs WHERE " + IMAGE_SQL + " AND status IN "
            "('running','uploading','sent_to_comfyui','sent_to_openrouter') LIMIT 1", IMAGE_MODES,
        ).fetchone()
        if active is not None:
            return None
        row = conn.execute("SELECT * FROM jobs WHERE " + IMAGE_SQL +
                           " AND status='queued' ORDER BY created_at,id LIMIT 1", IMAGE_MODES).fetchone()
        if row is None:
            return None
        settings = _settings(row)
        if generation_claims.METADATA_KEY in settings:
            raise GenerationClaimLost("GENERATION_QUEUED_CLAIM_INVALID")
        claim = generation_claims.Claim(str(row["id"]), str(row["user_id"]),
                                        uuid.uuid4().hex, worker_id)
        now = time.time()
        settings[generation_claims.METADATA_KEY] = {
            "version": 2, "token": claim.token, "workerId": worker_id,
            "leaseUntil": now + lease_seconds, "renewedAt": now,
            "issuedAt": now, "providerCommands": 0,
        }
        updated = conn.execute(
            "UPDATE jobs SET status='running',started_at=COALESCE(started_at,?),settings_json=? "
            "WHERE id=? AND status='queued'", (now_iso(), json.dumps(settings, ensure_ascii=False), claim.job_id),
        )
        if updated.rowcount != 1:
            raise GenerationClaimLost("GENERATION_CLAIM_LOST")
        request = dict(settings)
        request.pop(generation_claims.METADATA_KEY, None)
        request.pop("_generationAdmission", None)
        request.pop(generation_jobs.ADMIN_PROBE_METADATA_KEY, None)
        job = {
            "id": claim.job_id, "userId": claim.user_id, "mode": row["mode"], "provider": row["provider"],
            "status": "running", "progress": int(row["progress"] or 0), "request": request,
            "createdAt": row["created_at"], "startedAt": row["started_at"] or now_iso(),
            "tokenCost": settings.get("tokenCost"), "openrouterBilling": settings.get("openrouterBilling"),
        }
        return claim, job


def renew(connect, claim, *, lease_seconds=LEASE_SECONDS) -> None:
    with closing(connect()) as conn, conn:
        row = generation_claims.owned(conn, claim)
        settings = _settings(row)
        metadata = settings[generation_claims.METADATA_KEY]
        now = time.time()
        metadata.update(leaseUntil=now + lease_seconds, renewedAt=now)
        conn.execute("UPDATE jobs SET settings_json=? WHERE id=?",
                     (json.dumps(settings, ensure_ascii=False), claim.job_id))


def command_started(connect, claim) -> None:
    """Fence immediately before dispatch; retain evidence of uncertain effects."""
    with closing(connect()) as conn, conn:
        row = generation_claims.owned(conn, claim)
        settings = _settings(row)
        metadata = settings[generation_claims.METADATA_KEY]
        metadata["providerCommands"] = int(metadata.get("providerCommands", 0)) + 1
        metadata["lastCommandAt"] = time.time()
        conn.execute("UPDATE jobs SET settings_json=? WHERE id=?",
                     (json.dumps(settings, ensure_ascii=False), claim.job_id))


def abandon(connect, claim, *, reason="worker_connection_lost") -> None:
    """Revoke a lost stream immediately, before any local fallback can commit."""
    try:
        with closing(connect()) as conn, conn:
            row = generation_claims.owned(conn, claim)
            settings = _settings(row)
            settings[generation_claims.METADATA_KEY].update(leaseUntil=0, lossReason=reason)
            conn.execute("UPDATE jobs SET settings_json=? WHERE id=?",
                         (json.dumps(settings, ensure_ascii=False), claim.job_id))
    except GenerationClaimLost:
        pass


def expire(connect, refund_job, *, now=None) -> list[str]:
    """Resolve lost execution once; never submit another provider request."""
    timestamp = time.time() if now is None else now
    expired = []
    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute("SELECT * FROM jobs WHERE " + IMAGE_SQL + " AND status IN "
                            "('running','uploading','sent_to_comfyui','sent_to_openrouter')", IMAGE_MODES).fetchall()
        for row in rows:
            settings = _settings(row)
            claim = settings.get(generation_claims.METADATA_KEY)
            if not isinstance(claim, dict) or claim.get("version") != 2:
                continue
            deadline = claim.get("leaseUntil")
            if type(deadline) in (int, float) and math.isfinite(deadline) and deadline > timestamp:
                continue
            claim.setdefault("lossReason", "worker_heartbeat_expired")
            refund_job(conn, str(row["id"]), reason="worker_lease_expired")
            completed_at = now_iso()
            conn.execute("UPDATE jobs SET status='failed',progress=100,result_image_id=NULL,"
                         "error_message=?,completed_at=?,settings_json=? WHERE id=?",
                         ("Generation provider worker lease expired; operation was not retried.",
                          completed_at, json.dumps(settings, ensure_ascii=False), str(row["id"])))
            settle_trial_generation(conn, str(row["id"]), job_status="failed", now=completed_at)
            expired.append(str(row["id"]))
    return expired


class DurableWakeQueue:
    """The admission facade reads SQLite; no in-memory queue can lose a job."""
    def __init__(self, connect):
        self.connect = connect

    def qsize(self):
        with closing(self.connect()) as conn:
            return int(conn.execute("SELECT COUNT(*) FROM jobs WHERE " + IMAGE_SQL +
                                    " AND status='queued'", IMAGE_MODES).fetchone()[0])

    async def put(self, _job_id):
        return None

    async def get(self):
        raise RuntimeError("GENERATION_BACKEND_CONSUMER_FORBIDDEN")

    def task_done(self):
        raise RuntimeError("GENERATION_BACKEND_CONSUMER_FORBIDDEN")
