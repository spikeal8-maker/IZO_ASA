"""Small, import-safe HTTP boundary for Ollama discovery."""

from __future__ import annotations

import os
import time
from typing import Any

import httpx


DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"


def qwen_max_reasoning_body(body: dict[str, Any]) -> dict[str, Any]:
    """Keep the shared Qwen profile authoritative over legacy short-call settings."""
    if str(body.get("model", "")).lower() != "qwen3.8:27b":
        return body
    return {
        **body,
        "think": "xhigh",
        "keep_alive": -1,
        "options": {**body.get("options", {}), "num_ctx": 120000, "num_predict": -1},
    }


def ollama_base_url(value: str | None = None) -> str:
    """Return the configured Ollama origin without a trailing slash."""

    return (value if value is not None else os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)).rstrip("/")


async def fetch_ollama_models_status(
    *,
    base_url: str | None = None,
    timeout_seconds: float = 3,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Read ``/api/tags`` and preserve the legacy admin status payload."""

    resolved_base_url = ollama_base_url(base_url)
    client_options: dict[str, Any] = {"timeout": timeout_seconds}
    if transport is not None:
        client_options["transport"] = transport
    try:
        async with httpx.AsyncClient(**client_options) as client:
            response = await client.get(f"{resolved_base_url}/api/tags")
        response.raise_for_status()
        payload = response.json() if response.content else {}
        models = payload.get("models") if isinstance(payload, dict) and isinstance(payload.get("models"), list) else []
        return {"ok": True, "baseUrl": resolved_base_url, "models": models}
    except Exception as exc:
        return {
            "ok": False,
            "baseUrl": resolved_base_url,
            "models": [],
            "error": type(exc).__name__,
        }


async def request_ollama_chat_message(
    *,
    body: dict[str, Any],
    timeout_seconds: float,
    base_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[str, Any]:
    """POST an Ollama chat body and return legacy message content plus payload."""

    resolved_base_url = ollama_base_url(base_url)
    body = qwen_max_reasoning_body(body)
    if body.get("think") == "xhigh":
        timeout_seconds = max(timeout_seconds, 1800)
    client_options: dict[str, Any] = {"timeout": timeout_seconds}
    if transport is not None:
        client_options["transport"] = transport
    async with httpx.AsyncClient(**client_options) as client:
        response = await client.post(f"{resolved_base_url}/api/chat", json=body)
    payload = response.json() if response.content else {}
    if response.status_code >= 400:
        raise RuntimeError(f"Ollama вернула ошибку {response.status_code}.")
    message = payload.get("message") if isinstance(payload, dict) and isinstance(payload.get("message"), dict) else {}
    return str(message.get("content") or ""), payload


async def fetch_ollama_residency_status(
    *,
    base_url: str | None = None,
    timeout_seconds: float = 3,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Return the models currently loaded by Ollama, not merely installed."""

    resolved_base_url = ollama_base_url(base_url)
    client_options: dict[str, Any] = {"timeout": timeout_seconds}
    if transport is not None:
        client_options["transport"] = transport
    try:
        async with httpx.AsyncClient(**client_options) as client:
            response = await client.get(f"{resolved_base_url}/api/ps")
        response.raise_for_status()
        payload = response.json() if response.content else {}
        models = payload.get("models") if isinstance(payload, dict) and isinstance(payload.get("models"), list) else []
        return {"ok": True, "baseUrl": resolved_base_url, "models": models}
    except Exception as exc:
        return {"ok": False, "baseUrl": resolved_base_url, "models": [], "error": type(exc).__name__}


async def ensure_ollama_model_resident(
    *,
    model: str,
    timeout_seconds: float = 180,
    keep_alive: int | str = -1,
    base_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Load ``model`` when needed and verify that Ollama keeps it resident."""

    selected = model.strip()
    if not selected:
        raise RuntimeError("Локальная модель не выбрана.")
    resolved_base_url = ollama_base_url(base_url)
    started = time.monotonic()
    client_options: dict[str, Any] = {
        "timeout": httpx.Timeout(max(10.0, float(timeout_seconds)), connect=min(10.0, max(3.0, float(timeout_seconds)))),
    }
    if transport is not None:
        client_options["transport"] = transport
    async with httpx.AsyncClient(**client_options) as client:
        status = await client.get(f"{resolved_base_url}/api/ps")
        status.raise_for_status()
        running = status.json() if status.content else {}
        rows = running.get("models") if isinstance(running, dict) and isinstance(running.get("models"), list) else []
        resident = next((row for row in rows if str(row.get("name") or row.get("model") or "") == selected), None)
        if resident is None:
            response = await client.post(
                f"{resolved_base_url}/api/chat",
                json={
                    "model": selected,
                    "stream": False,
                    "think": False,
                    "keep_alive": keep_alive,
                    "messages": [{"role": "user", "content": "Ответь одним словом: готово"}],
                    "options": {"temperature": 0, "num_predict": 2},
                },
            )
            response.raise_for_status()
            status = await client.get(f"{resolved_base_url}/api/ps")
            status.raise_for_status()
            running = status.json() if status.content else {}
            rows = running.get("models") if isinstance(running, dict) and isinstance(running.get("models"), list) else []
            resident = next((row for row in rows if str(row.get("name") or row.get("model") or "") == selected), None)
        if resident is None:
            raise RuntimeError(f"Ollama не удержала модель {selected} в памяти.")
    return {
        "ok": True,
        "model": selected,
        "alreadyResident": time.monotonic() - started < 1.0,
        "latencyMs": round((time.monotonic() - started) * 1000),
        "sizeVram": int(resident.get("size_vram") or 0),
        "expiresAt": resident.get("expires_at"),
    }


async def unload_ollama_model(
    *,
    model: str,
    timeout_seconds: float = 30,
    base_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """Release a no-longer-selected Ollama model from memory."""

    selected = model.strip()
    if not selected:
        return
    resolved_base_url = ollama_base_url(base_url)
    client_options: dict[str, Any] = {"timeout": timeout_seconds}
    if transport is not None:
        client_options["transport"] = transport
    async with httpx.AsyncClient(**client_options) as client:
        response = await client.post(
            f"{resolved_base_url}/api/generate",
            json={"model": selected, "stream": False, "keep_alive": 0},
        )
    response.raise_for_status()
