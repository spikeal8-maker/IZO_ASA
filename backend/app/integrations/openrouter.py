"""Import-safe OpenRouter read-only HTTP boundaries."""

from __future__ import annotations

from typing import Any

import httpx


def parse_openrouter_text_models(payload: Any) -> list[dict[str, Any]]:
    """Convert the text-model catalog into the legacy admin payload."""

    rows = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), list) else []
    models: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        architecture = row.get("architecture") if isinstance(row.get("architecture"), dict) else {}
        inputs = architecture.get("input_modalities") if isinstance(architecture.get("input_modalities"), list) else []
        outputs = architecture.get("output_modalities") if isinstance(architecture.get("output_modalities"), list) else []
        if "text" not in inputs or "text" not in outputs:
            continue
        pricing = row.get("pricing") if isinstance(row.get("pricing"), dict) else {}
        try:
            input_per_million = float(pricing.get("prompt") or 0) * 1_000_000
            output_per_million = float(pricing.get("completion") or 0) * 1_000_000
        except (TypeError, ValueError):
            input_per_million = output_per_million = 0
        model_id = str(row.get("id") or "").strip()
        if not model_id:
            continue
        models.append({
            "id": model_id,
            "name": str(row.get("name") or model_id),
            "inputPerMillionUsd": round(input_per_million, 6),
            "outputPerMillionUsd": round(output_per_million, 6),
            "contextLength": int(row.get("context_length") or 0),
        })
    models.sort(key=lambda item: (item["name"].lower(), item["id"]))
    return models


async def fetch_openrouter_text_models(
    *,
    base_url: str,
    headers: dict[str, str],
    timeout_seconds: float = 15,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, Any]]:
    """Fetch and parse OpenRouter's text-capable model catalog."""

    client_options: dict[str, Any] = {"timeout": timeout_seconds}
    if transport is not None:
        client_options["transport"] = transport
    async with httpx.AsyncClient(**client_options) as client:
        response = await client.get(
            f"{base_url.rstrip('/')}/models?output_modalities=text",
            headers=headers,
        )
    response.raise_for_status()
    payload = response.json() if response.content else {}
    return parse_openrouter_text_models(payload)
