"""Small, import-safe HTTP boundary for Ollama discovery."""

from __future__ import annotations

import os
from typing import Any

import httpx


DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"


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
