from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx


class LtxComfyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ComfyLtxClient:
    base_url: str
    timeout_seconds: float = 15.0

    async def readiness(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(f"{self.base_url.rstrip('/')}/system_stats")
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return {"ready": False, "error": str(exc)}
        devices = ((payload.get("devices") or []) if isinstance(payload, dict) else [])
        gpu = next((item for item in devices if str(item.get("type") or "").lower() != "cpu"), None)
        return {
            "ready": gpu is not None,
            "device": (gpu or {}).get("name"),
            "vramTotal": (gpu or {}).get("vram_total"),
            "error": None if gpu is not None else "ComfyUI does not report a GPU device",
        }

    async def submit(self, prompt: dict[str, Any], *, client_id: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url.rstrip('/')}/prompt",
                    json={"prompt": prompt, "client_id": client_id},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LtxComfyError(f"ComfyUI rejected the LTX job: {exc}") from exc
        prompt_id = str(payload.get("prompt_id") or "")
        if not prompt_id:
            raise LtxComfyError(f"ComfyUI returned no prompt id: {payload}")
        return prompt_id

    async def status(self, prompt_id: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(
                    f"{self.base_url.rstrip('/')}/history/{quote(prompt_id, safe='')}"
                )
                response.raise_for_status()
                payload = response.json()
                item = payload.get(prompt_id) if isinstance(payload, dict) else None
                if not isinstance(item, dict):
                    # ComfyUI may briefly omit a newly submitted/running prompt
                    # from history.  Check the live queue before treating the
                    # prompt as lost after a supervisor restart.
                    queue_response = await client.get(f"{self.base_url.rstrip('/')}/queue")
                    queue_response.raise_for_status()
                    queue_payload = queue_response.json()
                    if _queue_contains_prompt(queue_payload, prompt_id):
                        return {"status": "in_progress", "progress": 55}
        except (httpx.HTTPError, ValueError) as exc:
            raise LtxComfyError(f"Cannot read the LTX job status: {exc}") from exc
        if not isinstance(item, dict):
            # A supervisor restart clears ComfyUI's volatile history.  The
            # application must distinguish that from a prompt that is merely
            # waiting, otherwise the persistent job remains pending forever.
            return {"status": "missing", "progress": 15}
        status = item.get("status") if isinstance(item.get("status"), dict) else {}
        if status.get("status_str") == "error":
            messages = status.get("messages") if isinstance(status.get("messages"), list) else []
            return {"status": "failed", "progress": 100, "error": str(messages[-1] if messages else "LTX failed")}
        output = _video_output(item.get("outputs"))
        if output:
            return {"status": "completed", "progress": 100, "output": output}
        return {"status": "in_progress", "progress": 55}

    async def free_memory(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url.rstrip('/')}/free",
                    json={"unload_models": True, "free_memory": True},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LtxComfyError(f"Cannot release LTX GPU memory: {exc}") from exc

    def view_url(self, output: dict[str, str]) -> str:
        filename = quote(output["filename"], safe="")
        subfolder = quote(output.get("subfolder") or "", safe="")
        kind = quote(output.get("type") or "output", safe="")
        return f"{self.base_url.rstrip('/')}/view?filename={filename}&subfolder={subfolder}&type={kind}"


def _video_output(outputs: Any) -> dict[str, str] | None:
    if not isinstance(outputs, dict):
        return None
    for output in outputs.values():
        if not isinstance(output, dict):
            continue
        candidates = output.get("gifs") or output.get("videos") or []
        if isinstance(candidates, list):
            for candidate in candidates:
                if isinstance(candidate, dict) and str(candidate.get("filename") or "").lower().endswith((".mp4", ".webm", ".mov")):
                    return {
                        "filename": str(candidate["filename"]),
                        "subfolder": str(candidate.get("subfolder") or ""),
                        "type": str(candidate.get("type") or "output"),
                    }
    return None


def _queue_contains_prompt(payload: Any, prompt_id: str) -> bool:
    if not isinstance(payload, dict):
        return False
    for key in ("queue_running", "queue_pending"):
        entries = payload.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, (list, tuple)) and len(entry) > 1 and str(entry[1]) == prompt_id:
                return True
            if isinstance(entry, dict) and str(entry.get("prompt_id") or "") == prompt_id:
                return True
    return False
