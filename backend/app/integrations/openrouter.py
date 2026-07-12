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


async def fetch_openrouter_key_details(
    *,
    base_url: str,
    key_headers: dict[str, str],
    credits_headers: dict[str, str],
    timeout_seconds: float = 15,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Fetch the legacy read-only key and credits status payload."""

    client_options: dict[str, Any] = {"timeout": timeout_seconds}
    if transport is not None:
        client_options["transport"] = transport
    resolved_base_url = base_url.rstrip("/")
    async with httpx.AsyncClient(**client_options) as client:
        response = await client.get(f"{resolved_base_url}/key", headers=key_headers)
        credits_response = await client.get(f"{resolved_base_url}/credits", headers=credits_headers)
    data = response.json() if response.content else {}
    if response.status_code >= 400:
        return {
            "ok": False,
            "status_code": response.status_code,
            "error": data.get("error") or data,
        }
    key_data = data.get("data") if isinstance(data.get("data"), dict) else data
    credits_payload = credits_response.json() if credits_response.content else {}
    credits_data = credits_payload.get("data") if isinstance(credits_payload.get("data"), dict) else credits_payload
    credits: dict[str, Any] = {
        "ok": credits_response.status_code < 400,
        "status_code": credits_response.status_code,
    }
    if credits["ok"] and isinstance(credits_data, dict):
        total_credits = credits_data.get("total_credits")
        total_usage = credits_data.get("total_usage")
        credits.update({"data": credits_data})
        if isinstance(total_credits, (int, float)) and isinstance(total_usage, (int, float)):
            credits["balance"] = round(float(total_credits) - float(total_usage), 6)
    else:
        credits["error"] = credits_payload.get("error") if isinstance(credits_payload, dict) else credits_payload
    return {
        "ok": True,
        "status_code": response.status_code,
        "data": key_data,
        "credits": credits,
    }


async def request_openrouter_chat_completion(
    *,
    base_url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout_seconds: float,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[int, Any]:
    """POST a chat completion and return its status plus parsed JSON payload."""

    client_options: dict[str, Any] = {"timeout": timeout_seconds}
    if transport is not None:
        client_options["transport"] = transport
    async with httpx.AsyncClient(**client_options) as client:
        response = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=body,
        )
    payload = response.json() if response.content else {}
    return response.status_code, payload
