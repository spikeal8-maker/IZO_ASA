"""Minimal public liveness and current database/media/worker readiness."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Response

from ...services.media_readiness import readiness_reason


@dataclass(frozen=True)
class HealthDependencies:
    media_dir: Callable[[], Path]
    release_id: Callable[[], str]
    collect_db_guard: Callable[[], dict[str, Any]]
    update_db_guard: Callable[[dict[str, Any]], None]
    worker_ready: Callable[[], bool] = lambda: True


def create_health_router(deps: HealthDependencies) -> APIRouter:
    router = APIRouter()

    @router.get("/api/health")
    async def health(response: Response) -> dict[str, Any]:
        guard = deps.collect_db_guard()
        deps.update_db_guard(guard)
        reason = await readiness_reason(deps.media_dir(), database_ready=bool(guard.get("ok")))
        if reason is None:
            try:
                worker_ready = deps.worker_ready()
            except Exception:
                worker_ready = False
            if not worker_ready:
                reason = "GENERATION_WORKER_UNAVAILABLE"
        response.status_code = 503 if reason else 200
        response.headers["Cache-Control"] = "no-store"
        payload = {"ok": not reason, "app": "izo-asa", "release_id": deps.release_id(), "ready": not reason}
        if reason:
            payload["reasonCode"] = reason
        return payload

    @router.get("/api/live")
    async def live() -> dict[str, Any]:
        return {"ok": True, "app": "izo-asa", "release_id": deps.release_id()}

    return router
