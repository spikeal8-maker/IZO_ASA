"""HTTP access policy for the closed beta and restored historical operations."""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from contextlib import closing

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from ..services.history_replay import HistoricalReplayBlocked, history_policy_for_connection


def closed_beta_enabled() -> bool:
    return os.getenv("IZO_CLOSED_BETA", "0").strip().lower() not in {"", "0", "false", "no", "off"}


def require_public_account_creation_allowed() -> None:
    if closed_beta_enabled():
        raise HTTPException(403, "closed_beta_registration_disabled")


def guard_generation_job(connection: Callable[[], sqlite3.Connection], job_id: str) -> None:
    with closing(connection()) as conn:
        history_policy_for_connection(conn).require_allowed("jobs", job_id)


async def historical_replay_blocked(_request: Request, exc: HistoricalReplayBlocked) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})
