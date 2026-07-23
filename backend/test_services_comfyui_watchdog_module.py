from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.services import comfyui_watchdog


def test_restart_request_is_atomic_fixed_data_not_a_command(tmp_path: Path) -> None:
    path = tmp_path / "request.json"
    payload = comfyui_watchdog.queue_hard_restart(
        path,
        job_id="job-1",
        prompt_id="prompt-1",
        reason="image_timeout",
        now=datetime(2026, 7, 23, tzinfo=timezone.utc),
        request_id="request-1",
    )
    assert payload is not None
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["Source"] == "image-generation-watchdog"
    assert persisted["JobId"] == "job-1"
    assert "Command" not in persisted
    assert list(tmp_path.glob("*.tmp")) == []


def test_history_poll_retries_http_timeout_and_returns_result() -> None:
    state = {"fetches": 0, "sleeps": 0, "recovered": 0, "now": 0.0}
    job = {"status": "running", "progress": 24}

    async def fetch(_prompt_id: str) -> dict:
        state["fetches"] += 1
        if state["fetches"] == 1:
            raise httpx.ReadTimeout("busy")
        return {"prompt-1": {"outputs": {}}}

    async def sleep(seconds: float) -> None:
        state["sleeps"] += 1
        state["now"] += seconds

    async def recover(_reason: str) -> None:
        state["recovered"] += 1

    result = asyncio.run(
        comfyui_watchdog.poll_prompt_history(
            prompt_id="prompt-1",
            job=job,
            timeout_seconds=300,
            fetch=fetch,
            recover=recover,
            monotonic=lambda: state["now"],
            sleep=sleep,
            transient_errors=(httpx.TimeoutException,),
        )
    )
    assert result == {"outputs": {}}
    assert state == {"fetches": 2, "sleeps": 1, "recovered": 0, "now": 2.0}
    assert job["comfyuiHistoryTimeouts"] == 1


def test_image_deadline_recovers_once_and_raises_readable_error() -> None:
    state = {"now": 0.0, "reasons": []}

    async def fetch(_prompt_id: str) -> dict:
        return {}

    async def sleep(seconds: float) -> None:
        state["now"] += seconds

    async def recover(reason: str) -> None:
        state["reasons"].append(reason)

    with pytest.raises(comfyui_watchdog.ComfyUIImageTimeout, match="300"):
        asyncio.run(
            comfyui_watchdog.poll_prompt_history(
                prompt_id="prompt-1",
                job={"status": "running", "progress": 24},
                timeout_seconds=300,
                fetch=fetch,
                recover=recover,
                monotonic=lambda: state["now"],
                sleep=sleep,
                transient_errors=(httpx.TimeoutException,),
            )
        )
    assert state["reasons"] == ["image_timeout"]


def test_recovery_gate_blocks_until_restart_request_is_consumed(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    gate = comfyui_watchdog.RecoveryGate(request_path, recovery_wait_seconds=20)
    state = {"now": 0.0, "interrupts": 0, "frees": 0, "availability": 0}

    async def interrupt() -> None:
        state["interrupts"] += 1

    async def free_memory() -> None:
        state["frees"] += 1

    async def available() -> bool:
        state["availability"] += 1
        return True

    async def sleep(seconds: float) -> None:
        state["now"] += seconds
        if request_path.exists():
            request_path.unlink()

    asyncio.run(
        gate.recover(
            prompt_id="prompt-1",
            job_id="job-1",
            reason="image_timeout",
            interrupt=interrupt,
            free_memory=free_memory,
            available=available,
            monotonic=lambda: state["now"],
            sleep=sleep,
        )
    )

    assert gate.blocked is False
    assert state == {"now": 2.0, "interrupts": 1, "frees": 2, "availability": 1}
