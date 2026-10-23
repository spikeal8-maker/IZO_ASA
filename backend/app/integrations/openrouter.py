"""Import-safe OpenRouter read-only HTTP boundaries."""

from __future__ import annotations

import asyncio
from typing import Any, Callable
from urllib.parse import urljoin

import httpx

from .generation_transport import client_options as generation_options


OPENROUTER_VIDEO_MODES = ("text_to_video", "image_to_video", "first_last_frame", "reference_to_video")
OPENROUTER_VIDEO_TIERS = ("mini", "plus", "pro", "business")
PUBLIC_TEMPORARY_FAILURE = (
    "Не удалось завершить генерацию из-за временного сбоя. "
    "Попробуйте ещё раз позже или обратитесь в поддержку."
)


class OpenRouterVideoRequestError(RuntimeError):
    """Provider rejection with a retained status code and sanitized text payload."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = int(status_code)
        self.detail = str(detail or "").strip()
        super().__init__(f"OpenRouter video request rejected ({self.status_code}): {self.detail or 'empty response'}")


def openrouter_video_public_error(error: OpenRouterVideoRequestError) -> str:
    """Convert provider diagnostics into a useful, user-safe Russian message."""

    detail = error.detail.lower()
    if any(marker in detail for marker in ("nsfw", "nudity", "sexual", "safety", "moderation", "content policy", "policy violation")):
        return "Провайдер отклонил изображение или описание из-за ограничений безопасности. Выберите другой кадр или измените описание."
    if any(marker in detail for marker in ("image_url", "image url", "download image", "fetch image", "invalid image", "unsupported image")):
        return "Провайдер не смог прочитать исходное изображение. Выберите другой кадр из галереи и попробуйте снова."
    if any(marker in detail for marker in ("aspect", "resolution", "duration", "unsupported", "invalid parameter", "invalid value")):
        return "Модель не приняла выбранные параметры видео. Измените формат, качество или длительность."
    if error.status_code == 400:
        return "Модель отклонила исходное изображение или параметры. Выберите другой кадр либо измените настройки."
    if error.status_code in {401, 403}:
        return PUBLIC_TEMPORARY_FAILURE
    if error.status_code == 402:
        return PUBLIC_TEMPORARY_FAILURE
    if error.status_code == 429:
        return "Видеосервис перегружен. Подождите немного и попробуйте снова."
    return "Видеосервис не ответил. Попробуйте снова через несколько минут."


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
    try:
        created = int(model.get("created") or 0)
    except (TypeError, ValueError):
        created = 0
    capability = {
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
    if created > 0:
        capability["created"] = created
    return capability


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

    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    candidates = [
        payload.get("cost"),
        payload.get("total_cost"),
        payload.get("total_cost_usd"),
        usage.get("cost"),
        usage.get("total_cost"),
        usage.get("total_cost_usd"),
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


def format_openrouter_public_error(
    status_code: int,
    data: dict[str, Any],
    *,
    truncate: Callable[[str, int], str],
) -> str:
    """Map a provider response to the established application-safe Russian error."""

    message = openrouter_error_message(data)
    if is_openrouter_size_error(data):
        return "Модель не приняла выбранный формат изображения. Попробуйте квадратный формат или другую модель."
    if status_code in {401, 403}:
        return PUBLIC_TEMPORARY_FAILURE
    if status_code == 402:
        return PUBLIC_TEMPORARY_FAILURE
    if status_code == 429:
        return "Сервис временно перегружен. Подождите немного и попробуйте снова."
    return PUBLIC_TEMPORARY_FAILURE


def normalize_openrouter_image_response_metadata(data: dict[str, Any]) -> dict[str, Any]:
    """Select the safe metadata retained beside a generated gallery image."""

    return {
        "response_id": data.get("id") or data.get("response_id"),
        "usage": data.get("usage") if isinstance(data.get("usage"), dict) else {},
        "cost_usd": extract_openrouter_generation_cost(data),
        "raw": {key: value for key, value in data.items() if key not in {"data", "images", "output"}},
    }


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
        if input_per_million < 0 or output_per_million < 0:
            continue
        model_id = str(row.get("id") or "").strip()
        if not model_id:
            continue
        model = {
            "id": model_id,
            "name": str(row.get("name") or model_id),
            "provider": model_id.split("/", 1)[0],
            "inputPerMillionUsd": round(input_per_million, 6),
            "outputPerMillionUsd": round(output_per_million, 6),
            "contextLength": int(row.get("context_length") or 0),
        }
        try:
            created = int(row.get("created"))
        except (TypeError, ValueError):
            created = 0
        if created > 0:
            model["created"] = created
        models.append(model)
    models.sort(key=lambda item: (item["name"].lower(), item["id"]))
    return models


def parse_openrouter_audio_input_models(payload: Any) -> list[dict[str, Any]]:
    """Return models that accept audio and can answer with transcription text."""

    rows = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), list) else []
    models: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        architecture = row.get("architecture") if isinstance(row.get("architecture"), dict) else {}
        inputs = architecture.get("input_modalities") if isinstance(architecture.get("input_modalities"), list) else []
        outputs = architecture.get("output_modalities") if isinstance(architecture.get("output_modalities"), list) else []
        if "audio" not in inputs or "text" not in outputs:
            continue
        model_id = str(row.get("id") or "").strip()
        if not model_id:
            continue
        pricing = row.get("pricing") if isinstance(row.get("pricing"), dict) else {}
        try:
            input_per_million = float(pricing.get("prompt") or 0) * 1_000_000
            output_per_million = float(pricing.get("completion") or 0) * 1_000_000
        except (TypeError, ValueError):
            input_per_million = output_per_million = 0
        if input_per_million < 0 or output_per_million < 0:
            continue
        models.append({
            "id": model_id,
            "name": str(row.get("name") or model_id),
            "inputPerMillionUsd": round(input_per_million, 6),
            "outputPerMillionUsd": round(output_per_million, 6),
            "contextLength": int(row.get("context_length") or 0),
        })
    models.sort(key=lambda item: (item["inputPerMillionUsd"] + item["outputPerMillionUsd"], item["name"].lower()))
    return models


def parse_openrouter_video_models(payload: Any) -> list[dict[str, Any]]:
    """Normalize the dedicated OpenRouter video catalog for the admin UI."""

    rows = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), list) else []
    models: list[dict[str, Any]] = []
    reference_markers = (
        "reference-to-video",
        "reference images",
        "set of reference images",
        "multimodal reference",
    )
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = str(row.get("id") or "").strip()
        if not model_id:
            continue

        def string_list(key: str) -> list[str]:
            value = row.get(key)
            if not isinstance(value, list):
                return []
            return [str(item).strip() for item in value if str(item).strip()]

        durations: list[int] = []
        for value in row.get("supported_durations") or []:
            try:
                duration = int(value)
            except (TypeError, ValueError):
                continue
            if duration > 0 and duration not in durations:
                durations.append(duration)
        durations.sort()

        pricing_source = row.get("pricing_skus") if isinstance(row.get("pricing_skus"), dict) else {}
        pricing: dict[str, float] = {}
        for key, value in pricing_source.items():
            try:
                amount = float(value)
            except (TypeError, ValueError):
                continue
            if amount >= 0:
                pricing[str(key)] = amount

        frame_images = string_list("supported_frame_images")
        description = str(row.get("description") or "").strip()
        description_lower = description.lower()
        modes = ["text_to_video"]
        if "first_frame" in frame_images:
            modes.append("image_to_video")
        if "first_frame" in frame_images and "last_frame" in frame_images:
            modes.append("first_last_frame")
        reference_evidence = "description" if any(marker in description_lower for marker in reference_markers) else None
        if reference_evidence:
            modes.append("reference_to_video")
        try:
            created = int(row.get("created") or 0)
        except (TypeError, ValueError):
            created = 0

        models.append({
            "id": model_id,
            "canonicalSlug": str(row.get("canonical_slug") or "").strip(),
            "name": str(row.get("name") or model_id).strip(),
            "description": description,
            "created": created,
            "supportedResolutions": string_list("supported_resolutions"),
            "supportedAspectRatios": string_list("supported_aspect_ratios"),
            "supportedSizes": string_list("supported_sizes"),
            "supportedDurations": durations,
            "supportedFrameImages": frame_images,
            "generateAudio": row.get("generate_audio") if isinstance(row.get("generate_audio"), bool) else None,
            "seed": row.get("seed") if isinstance(row.get("seed"), bool) else None,
            "pricingSkus": pricing,
            "allowedParameters": string_list("allowed_passthrough_parameters"),
            "modes": modes,
            "referenceEvidence": reference_evidence,
        })
    models.sort(key=lambda item: (item["name"].lower(), item["id"]))
    return models


def normalize_openrouter_video_config(raw: Any, catalog: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep only catalog-backed video models and known product modes/tiers."""

    source = raw if isinstance(raw, dict) else {}
    enabled_source = source.get("enabled") if isinstance(source.get("enabled"), dict) else {}
    access_source = source.get("access") if isinstance(source.get("access"), dict) else {}
    models_by_mode = {
        mode: {
            str(model.get("id") or "")
            for model in catalog
            if isinstance(model, dict) and mode in (model.get("modes") or []) and model.get("id")
        }
        for mode in OPENROUTER_VIDEO_MODES
    }
    catalog_ids = set().union(*models_by_mode.values()) if models_by_mode else set()
    raw_published = source.get("published")
    legacy_published: set[str] = set()
    for mode in OPENROUTER_VIDEO_MODES:
        mode_enabled = enabled_source.get(mode)
        if isinstance(mode_enabled, list):
            legacy_published.update(str(value) for value in mode_enabled)
        mode_access = access_source.get(mode)
        if isinstance(mode_access, dict):
            for tier_values in mode_access.values():
                if isinstance(tier_values, list):
                    legacy_published.update(str(value) for value in tier_values)
    published = sorted({
        str(value) for value in (raw_published if isinstance(raw_published, list) else legacy_published)
        if str(value) in catalog_ids
    })
    published_set = set(published)
    enabled: dict[str, list[str]] = {}
    access: dict[str, dict[str, list[str]]] = {}
    for mode in OPENROUTER_VIDEO_MODES:
        allowed = models_by_mode[mode]
        values = enabled_source.get(mode) if isinstance(enabled_source.get(mode), list) else []
        normalized_enabled = sorted({str(value) for value in values if str(value) in allowed and str(value) in published_set})
        mode_access_source = access_source.get(mode) if isinstance(access_source.get(mode), dict) else {}
        mode_access: dict[str, list[str]] = {}
        for tier in OPENROUTER_VIDEO_TIERS:
            tier_values = mode_access_source.get(tier) if isinstance(mode_access_source.get(tier), list) else []
            normalized_tier = sorted({str(value) for value in tier_values if str(value) in allowed and str(value) in published_set})
            if normalized_tier:
                mode_access[tier] = normalized_tier
                normalized_enabled = sorted(set(normalized_enabled).union(normalized_tier))
        if normalized_enabled:
            enabled[mode] = normalized_enabled
        if mode_access:
            access[mode] = mode_access
    return {"published": published, "enabled": enabled, "access": access}


async def fetch_openrouter_text_models(
    *,
    base_url: str,
    headers: dict[str, str],
    timeout_seconds: float = 15,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, Any]]:
    """Fetch and parse OpenRouter's text-capable model catalog."""

    client_options: dict[str, Any] = {"timeout": timeout_seconds}
    client_options = generation_options(client_options, transport)
    async with httpx.AsyncClient(**client_options) as client:
        response = await client.get(
            f"{base_url.rstrip('/')}/models?output_modalities=text",
            headers=headers,
        )
    response.raise_for_status()
    payload = response.json() if response.content else {}
    return parse_openrouter_text_models(payload)


async def fetch_openrouter_audio_input_models(
    *,
    base_url: str,
    headers: dict[str, str],
    timeout_seconds: float = 15,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, Any]]:
    """Fetch the OpenRouter catalog restricted to audio-input, text-output models."""

    client_options: dict[str, Any] = {"timeout": timeout_seconds}
    client_options = generation_options(client_options, transport)
    async with httpx.AsyncClient(**client_options) as client:
        response = await client.get(
            f"{base_url.rstrip('/')}/models?input_modalities=audio&output_modalities=text",
            headers=headers,
        )
    response.raise_for_status()
    payload = response.json() if response.content else {}
    return parse_openrouter_audio_input_models(payload)


async def fetch_openrouter_video_models(
    *,
    base_url: str,
    headers: dict[str, str],
    timeout_seconds: float = 20,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, Any]]:
    """Fetch the first-party OpenRouter video-model catalog."""

    client_options: dict[str, Any] = {"timeout": timeout_seconds}
    client_options = generation_options(client_options, transport)
    async with httpx.AsyncClient(**client_options) as client:
        response = await client.get(
            f"{base_url.rstrip('/')}/videos/models",
            headers=headers,
        )
    response.raise_for_status()
    payload = response.json() if response.content else {}
    return parse_openrouter_video_models(payload)


async def submit_openrouter_video(
    *,
    base_url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: float = 30,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Submit one asynchronous video job using OpenRouter's native endpoint."""

    client_options: dict[str, Any] = {"timeout": timeout_seconds}
    client_options = generation_options(client_options, transport)
    async with httpx.AsyncClient(**client_options) as client:
        response = await client.post(f"{base_url.rstrip('/')}/videos", headers=headers, json=payload)
    if response.is_error:
        try:
            raw = response.json() if response.content else {}
        except ValueError:
            raw = response.text
        if isinstance(raw, dict):
            detail = openrouter_error_message(raw)
        else:
            detail = str(raw or "")
        raise OpenRouterVideoRequestError(response.status_code, detail[:1000])
    data = response.json() if response.content else {}
    if not isinstance(data, dict) or not str(data.get("id") or "").strip():
        raise RuntimeError("OpenRouter did not return a video job id.")
    return data


async def poll_openrouter_video(
    *,
    base_url: str,
    headers: dict[str, str],
    job_id: str,
    polling_url: str | None = None,
    timeout_seconds: float = 30,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Read one video job state without starting an unbounded server poll loop."""

    target = str(polling_url or "").strip()
    if not target.startswith(("http://", "https://")):
        target = urljoin(f"{base_url.rstrip('/')}/", target) if target else f"{base_url.rstrip('/')}/videos/{job_id}"
    client_options: dict[str, Any] = {"timeout": timeout_seconds}
    client_options = generation_options(client_options, transport)
    async with httpx.AsyncClient(**client_options) as client:
        response = await client.get(target, headers=headers)
    response.raise_for_status()
    data = response.json() if response.content else {}
    if not isinstance(data, dict):
        raise RuntimeError("OpenRouter returned an invalid video job response.")
    return data


async def fetch_openrouter_key_details(
    *,
    base_url: str,
    key_headers: dict[str, str],
    credits_headers: dict[str, str],
    timeout_seconds: float = 15,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Probe ordinary sk-or keys via GET /key; management /credits is optional.

    No paid API operation or user key is ever echoed in provider diagnostics.
    """

    _ = credits_headers  # Management key is deliberately not used in this probe.
    options = generation_options({"timeout": timeout_seconds, "follow_redirects": False}, transport)
    resolved_base_url = base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(**options) as client:
            response = await client.get(f"{resolved_base_url}/key", headers=key_headers)
    except httpx.TimeoutException:
        return {"ok": False, "status_code": None, "error": "OPENROUTER_TIMEOUT",
                "credits": {"ok": False, "skipped": True, "error": "MANAGEMENT_KEY_REQUIRED"}}
    except httpx.HTTPError:
        return {"ok": False, "status_code": None, "error": "OPENROUTER_NETWORK_UNAVAILABLE",
                "credits": {"ok": False, "skipped": True, "error": "MANAGEMENT_KEY_REQUIRED"}}
    codes = {400: "OPENROUTER_REQUEST_INVALID", 401: "OPENROUTER_KEY_INVALID",
             403: "OPENROUTER_KEY_FORBIDDEN", 429: "OPENROUTER_RATE_LIMIT"}
    if response.status_code != 200:
        return {"ok": False, "status_code": response.status_code,
                "error": codes.get(response.status_code, "OPENROUTER_PROVIDER_UNAVAILABLE"),
                "credits": {"ok": False, "skipped": True, "error": "MANAGEMENT_KEY_REQUIRED"}}
    try:
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise ValueError("malformed key response")
    except (ValueError, TypeError):
        return {"ok": False, "status_code": 502, "error": "OPENROUTER_RESPONSE_INVALID",
                "credits": {"ok": False, "skipped": True, "error": "MANAGEMENT_KEY_REQUIRED"}}
    # Only return documented non-secret accounting fields, never arbitrary provider JSON.
    allowlist = ("label", "limit", "limit_remaining", "usage", "usage_daily",
                 "usage_weekly", "usage_monthly", "is_free_tier", "rate_limit",
                 "include_byok_in_limit", "allowed_data_regions")
    safe = {name: data[name] for name in allowlist if name in data}
    return {"ok": True, "status_code": 200, "data": safe,
            "credits": {"ok": False, "skipped": True, "error": "MANAGEMENT_KEY_REQUIRED"}}


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
    client_options = generation_options(client_options, transport)
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
    client_options = generation_options(client_options, transport)
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
