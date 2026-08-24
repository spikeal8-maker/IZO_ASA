"""Authenticated provider-neutral Phone job API."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from ...services.phone_jobs import list_phone_jobs, normalize_phone_job, phone_job_modality


@dataclass(frozen=True)
class PhoneJobDependencies:
    require_trusted_user: Callable[[Request], dict[str, Any]]
    connect_db: Callable[[], Any]
    read_image_job: Callable[[str, Request], Awaitable[dict[str, Any]] | dict[str, Any]]
    read_video_job: Callable[[str, Request], Awaitable[dict[str, Any]] | dict[str, Any]]


async def _await_payload(value: Awaitable[dict[str, Any]] | dict[str, Any]) -> dict[str, Any]:
    return await value if inspect.isawaitable(value) else value


def create_phone_jobs_router(deps: PhoneJobDependencies) -> APIRouter:
    router = APIRouter(prefix="/api/phone/v1/jobs", tags=["phone-v1"])

    @router.get("")
    async def phone_jobs(
        request: Request,
        active: bool = True,
        limit: int = Query(default=30, ge=1, le=60),
    ) -> dict[str, Any]:
        user_id = deps.require_trusted_user(request).get("legacy_user_id")
        if not user_id:
            raise HTTPException(404, "Пользователь не найден.")
        with deps.connect_db() as conn:
            items = list_phone_jobs(conn, str(user_id), active_only=active, limit=limit)
        return {"ok": True, "items": items}

    @router.get("/{job_id}")
    async def phone_job(job_id: str, request: Request) -> dict[str, Any]:
        trusted = deps.require_trusted_user(request)
        user_id = trusted.get("legacy_user_id")
        if not user_id:
            raise HTTPException(404, "Задание не найдено.")
        with deps.connect_db() as conn:
            row = conn.execute("SELECT mode FROM jobs WHERE id=? AND user_id=?", (job_id, user_id)).fetchone()
        if row is None:
            raise HTTPException(404, "Задание не найдено.")
        modality = phone_job_modality(row["mode"])
        if modality == "video":
            payload = await _await_payload(deps.read_video_job(job_id, request))
        elif modality == "image":
            payload = await _await_payload(deps.read_image_job(job_id, request))
        else:
            raise HTTPException(409, "Этот тип задания ещё не подключён к Phone API.")
        return {"ok": True, "job": normalize_phone_job(payload, modality=modality)}

    return router
