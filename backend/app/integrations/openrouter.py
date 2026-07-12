"""Import-safe OpenRouter read-only HTTP boundaries."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx


def _parameter_names(parameters: Any) -> list[str]:
    return sorted(str(key) for key in parameters.keys()) if isinstance(parameters, dict) else []


def _reference_limit(parameters: Any) -> int:
    descriptor = parameters.get("input_references") if isinstance(parameters, dict) else None
    if not isinstance(descriptor, dict):
        return 0
    try:
        return max(0, int(descriptor.get("max") or 0))
    except (TypeError, ValueError):
        return 0


def normalize_openrouter_model_capability(model: dict[str, Any]) -> dict[str, Any]:
    """Normalize one OpenRouter image-model document for application policy."""

    architecture = model.get("architecture") if isinstance(model.get("architecture"), dict) else {}
    inputs = sorted(str(value) for value in architecture.get("input_modalities", []) if isinstance(value, str))
    outputs = sorted(str(value) for value in architecture.get("output_modalities", []) if isinstance(value, str))
    parameters = model.get("supported_parameters") if isinstance(model.get("supported_parameters"), dict) else {}
    parameter_names = _parameter_names(parameters)
    max_references = _reference_limit(parameters)
    background = parameters.get("background") if isinstance(parameters.get("background"), dict) else {}
    background_values = [str(value) for value in background.get("values", []) if isinstance(value, str)]
    image_output = "image" in outputs
    modes: list[str] = []
    if "text" in inputs and image_output:
        modes.append("text_to_image")
    if image_output and max_references >= 1:
        modes.extend(["image_to_image", "paint"])
    if image_output and max_references >= 2:
        modes.append("edit")
    if image_output and any(key in parameters for key in ("mask", "mask_image", "inpaint")):
        modes.append("inpaint")
    if image_output and any(key in parameters for key in ("outpaint", "outpaint_mask", "canvas")):
        modes.append("outpaint")
    if image_output and max_references >= 1 and "transparent" in background_values:
        modes.append("remove_background")
    return {
        "id": str(model.get("id") or ""),
        "name": str(model.get("name") or model.get("id") or ""),
        "description": str(model.get("description") or ""),
        "inputModalities": inputs,
        "outputModalities": outputs,
        "parameters": parameter_names,
        "parameterDescriptors": parameters,
        "maxInputReferences": max_references,
        "supportsStreaming": bool(model.get("supports_streaming")),
        "modes": sorted(set(modes)),
        "features": {
            "seed": "seed" in parameters,
            "quality": "quality" in parameters,
            "aspectRatio": "aspect_ratio" in parameters,
            "resolution": "resolution" in parameters,
            "transparentBackground": "transparent" in background_values,
            "multipleOutputs": isinstance(parameters.get("n"), dict) and int(parameters["n"].get("max") or 1) > 1,
        },
    }


def normalize_openrouter_endpoint_capability(
    model: dict[str, Any],
    endpoint: dict[str, Any],
) -> dict[str, Any]:
    """Normalize one endpoint while preserving its provider pinning metadata."""

    capability = normalize_openrouter_model_capability({
        **model,
        "supported_parameters": endpoint.get("supported_parameters") or {},
    })
    capability.update({
        "endpointVerified": True,
        "providerName": str(endpoint.get("provider_name") or ""),
        "providerSlug": str(endpoint.get("provider_slug") or ""),
        "providerTag": str(endpoint.get("provider_tag") or ""),
        "pricing": endpoint.get("pricing") if isinstance(endpoint.get("pricing"), list) else [],
        "allowedPassthroughParameters": endpoint.get("allowed_passthrough_parameters") if isinstance(endpoint.get("allowed_passthrough_parameters"), list) else [],
    })
    return capability


def extract_openrouter_generation_cost(payload: dict[str, Any]) -> float | None:
    """Return the first numeric cost reported by an OpenRouter response."""

    candidates = [
        payload.get("cost"),
        payload.get("total_cost"),
        payload.get("total_cost_usd"),
        (payload.get("usage") or {}).get("cost"),
        (payload.get("usage") or {}).get("total_cost"),
        (payload.get("usage") or {}).get("total_cost_usd"),
    ]
    for value in candidates:
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def select_openrouter_first_image(payload: dict[str, Any]) -> dict[str, Any]:
    """Select the first supported image shape from an OpenRouter response."""

    data = payload.get("data")
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            return first
    images_data = payload.get("images")
    if isinstance(images_data, list) and images_data:
        first = images_data[0]
        if isinstance(first, dict):
            return first
        if isinstance(first, str):
            return {"url": first}
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if isinstance(item, dict):
                if item.get("b64_json") or item.get("url"):
                    return item
                content = item.get("content")
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and (part.get("b64_json") or part.get("url")):
                            return part
    raise RuntimeError("OpenRouter не вернул изображение в ответе.")


def extract_openrouter_error_payload(data: dict[str, Any]) -> Any:
    return data.get("error") if isinstance(data, dict) else data


def openrouter_error_message(data: dict[str, Any]) -> str:
    """Normalize provider and top-level OpenRouter error payloads to text."""

    payload = extract_openrouter_error_payload(data)
    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("error")
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        provider = metadata.get("provider_name")
        if isinstance(message, str) and message.strip():
            return f"{provider}: {message}" if provider else message
    if isinstance(payload, str):
        return payload
    return str(payload or data or "")


def is_openrouter_size_error(data: dict[str, Any]) -> bool:
    """Classify size/aspect validation failures without application wording."""

    message = openrouter_error_message(data).lower()
    return any(marker in message for marker in ("invalid size", "image size", "size ", "aspect", "invalid_value", "pixels"))


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


async def fetch_openrouter_image_model_documents(
    *,
    base_url: str,
    headers: dict[str, str],
    timeout_seconds: float = 20,
    max_concurrency: int = 8,
    endpoint_base_url: str = "https://openrouter.ai",
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, Any]]:
    """Collect image-model rows and optional endpoint metadata documents."""

    client_options: dict[str, Any] = {
        "timeout": timeout_seconds,
        "follow_redirects": True,
    }
    if transport is not None:
        client_options["transport"] = transport
    async with httpx.AsyncClient(**client_options) as client:
        response = await client.get(f"{base_url.rstrip('/')}/images/models", headers=headers)
        response.raise_for_status()
        payload = response.json() if response.content else {}
        rows = payload.get("data") if isinstance(payload, dict) else []
        semaphore = asyncio.Semaphore(max(1, max_concurrency))

        async def load_document(item: dict[str, Any]) -> dict[str, Any]:
            endpoint_path = str(item.get("endpoints") or "").strip()
            document = {"model": item, "endpoint_status": None, "endpoints": []}
            if not endpoint_path:
                return document
            endpoint_url = endpoint_path if endpoint_path.startswith("http") else f"{endpoint_base_url.rstrip('/')}{endpoint_path}"
            try:
                async with semaphore:
                    endpoint_response = await client.get(endpoint_url, headers=headers)
                endpoint_payload = endpoint_response.json() if endpoint_response.content else {}
                endpoints = endpoint_payload.get("endpoints") if isinstance(endpoint_payload, dict) else []
                candidates = [entry for entry in endpoints if isinstance(entry, dict)]
                return {
                    "model": item,
                    "endpoint_status": endpoint_response.status_code,
                    "endpoints": candidates,
                }
            except Exception:
                return document

        return await asyncio.gather(*(
            load_document(item)
            for item in rows
            if isinstance(item, dict) and item.get("id")
        ))
