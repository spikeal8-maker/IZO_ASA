"""Image-only ComfyUI timeout policy and privileged recovery hand-off."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping
from uuid import uuid4


class ComfyUIImageTimeout(TimeoutError):
    """A bounded image generation exceeded its end-to-end deadline."""


class RecoveryGate:
    """Serialize application submissions around one privileged worker restart."""

    def __init__(self, request_path: Path | None, recovery_wait_seconds: float) -> None:
        self.request_path = request_path
        self.recovery_wait_seconds = recovery_wait_seconds
        self.blocked = False

    def request_pending(self) -> bool:
        return self.request_path is not None and self.request_path.exists()

    async def wait(
        self,
        *,
        available: Callable[[], Awaitable[bool]],
        sleep: Callable[[float], Awaitable[None]],
    ) -> None:
        while self.blocked or self.request_pending():
            if not self.request_pending() and await available():
                self.blocked = False
                return
            await sleep(2)

    async def recover(
        self,
        *,
        prompt_id: str,
        job_id: str,
        reason: str,
        interrupt: Callable[[], Awaitable[None]],
        free_memory: Callable[[], Awaitable[None]],
        available: Callable[[], Awaitable[bool]],
        monotonic: Callable[[], float],
        sleep: Callable[[float], Awaitable[None]],
    ) -> None:
        self.blocked = True
        await interrupt()
        try:
            await free_memory()
        except Exception:
            pass
        queue_hard_restart(
            self.request_path,
            job_id=job_id,
            prompt_id=prompt_id,
            reason=reason,
        )
        deadline = monotonic() + self.recovery_wait_seconds
        while monotonic() < deadline:
            if not self.request_pending() and await available():
                self.blocked = False
                try:
                    await free_memory()
                except Exception:
                    pass
                return
            await sleep(2)


def default_restart_request_path(
    environment: Mapping[str, str] | None = None,
    *,
    platform_name: str | None = None,
) -> Path | None:
    source = os.environ if environment is None else environment
    configured = str(source.get("COMFYUI_WATCHDOG_REQUEST_PATH", "")).strip()
    if configured:
        return Path(configured)
    if (platform_name or os.name) == "nt":
        return Path(r"C:\IZO_ASA\runtime\comfyui-watchdog\request.json")
    return None


def queue_hard_restart(
    path: Path | None,
    *,
    job_id: str,
    prompt_id: str,
    reason: str,
    now: datetime | None = None,
    request_id: str | None = None,
) -> dict[str, Any] | None:
    """Atomically request one fixed ComfyUI service restart from SYSTEM."""

    if path is None:
        return None
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload = {
        "SchemaVersion": 1,
        "RequestId": request_id or str(uuid4()),
        "RequestedAt": timestamp.isoformat(),
        "JobId": job_id[:160],
        "PromptId": prompt_id[:160],
        "Reason": reason[:300],
        "Source": "image-generation-watchdog",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return payload


async def poll_prompt_history(
    *,
    prompt_id: str,
    job: dict[str, Any],
    timeout_seconds: float,
    fetch: Callable[[str], Awaitable[dict[str, Any]]],
    recover: Callable[[str], Awaitable[None]],
    monotonic: Callable[[], float],
    sleep: Callable[[float], Awaitable[None]],
    transient_errors: tuple[type[BaseException], ...],
    poll_seconds: float = 2,
) -> dict[str, Any]:
    """Poll through transient HTTP stalls and recover exactly at the deadline."""

    deadline = monotonic() + timeout_seconds
    transient_failures = 0
    while monotonic() < deadline:
        if job.get("status") == "cancelled":
            await recover("cancelled")
            raise RuntimeError("Задача отменена")
        try:
            payload = await fetch(prompt_id)
        except transient_errors:
            transient_failures += 1
            job["comfyuiHistoryTimeouts"] = transient_failures
            await sleep(poll_seconds)
            continue
        if prompt_id in payload:
            return payload[prompt_id]
        job["progress"] = min(94, int(job.get("progress", 24)) + 2)
        await sleep(poll_seconds)
    await recover("image_timeout")
    raise ComfyUIImageTimeout(
        f"Генерация изображения превысила лимит {int(timeout_seconds)} с; "
        "ComfyUI остановлен и видеопамять сбрасывается."
    )
