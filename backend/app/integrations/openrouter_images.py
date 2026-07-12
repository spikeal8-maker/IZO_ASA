"""Pure OpenRouter image request planning helpers."""

from __future__ import annotations

import math
from typing import Any, Callable


def requested_orientation(width: int, height: int) -> str:
    if width > height:
        return "horizontal"
    if height > width:
        return "vertical"
    return "square"


def openrouter_ratio_size(width: int, height: int) -> str:
    if not width or not height:
        return "auto"
    divisor = math.gcd(int(width), int(height)) or 1
    return f"{int(width) // divisor}:{int(height) // divisor}"


def openrouter_descriptor_values(capability: dict[str, Any] | None, key: str) -> list[str]:
    descriptors = (capability or {}).get("parameterDescriptors")
    descriptor = descriptors.get(key) if isinstance(descriptors, dict) else None
    values = descriptor.get("values") if isinstance(descriptor, dict) else None
    return [str(value) for value in values] if isinstance(values, list) else []


def image_edit_influence_instruction(strength: float) -> str:
    percent = max(0, min(100, round(float(strength) * 100)))
    if percent <= 24:
        behavior = "Make only minimal, local changes. Preserve composition, identity, geometry, colors, lighting, camera, and nearly all source details."
    elif percent <= 49:
        behavior = "Edit conservatively. Preserve the composition and recognizability of the source while applying the requested change clearly."
    elif percent <= 74:
        behavior = "Apply a noticeable transformation, but keep the main subjects, layout, perspective, and important source details recognizable."
    elif percent <= 89:
        behavior = "Follow the edit prompt strongly. Preserve only the source elements that the prompt does not ask to change."
    else:
        behavior = "Freely reinterpret the source according to the edit prompt while retaining it as the visual reference."
    return f"Image edit influence: {percent}%. {behavior} Do not ignore the supplied reference image."


def build_openrouter_image_request_body(
    payload: Any,
    model: str,
    request_plan: dict[str, Any],
    capability: dict[str, Any],
    *,
    reference_resolver: Callable[[str | None], str],
) -> dict[str, Any]:
    """Build an OpenRouter image body without owning local-media access."""

    if payload.mode not in (capability.get("modes") or []):
        raise RuntimeError(f"Модель {model} не поддерживает режим {payload.mode} по актуальным данным OpenRouter.")
    parameters = set(capability.get("parameters") or [])
    body: dict[str, Any] = {"model": model, "prompt": payload.prompt, "n": 1}
    provider_tag = str(capability.get("providerTag") or "").strip()
    if provider_tag:
        body["provider"] = {"only": [provider_tag], "allow_fallbacks": False}
    if request_plan.get("aspect_ratio") and "aspect_ratio" in parameters:
        body["aspect_ratio"] = request_plan["aspect_ratio"]
    if request_plan.get("resolution") and "resolution" in parameters:
        body["resolution"] = request_plan["resolution"]
    if "aspect_ratio" not in body and request_plan.get("size"):
        body["size"] = request_plan["size"]
    if payload.mode == "image_to_image":
        body["prompt"] = f"{payload.prompt.strip()}\n\n{image_edit_influence_instruction(payload.strength)}".strip()
        body["input_references"] = [{
            "type": "image_url",
            "image_url": {"url": reference_resolver(payload.inputImage1)},
        }]
    elif payload.mode == "edit":
        references = [
            item for item in sorted(payload.inputImages, key=lambda value: value.index or 0)
            if item.image
        ]
        max_references = min(4, int(capability.get("maxInputReferences") or 0))
        if len(references) < 2:
            raise RuntimeError("Для «Сборки» нужны основа и хотя бы один референс.")
        if len(references) > max_references:
            raise RuntimeError(f"Модель {model} принимает не больше {max_references} изображений для «Сборки».")
        body["input_references"] = [
            {"type": "image_url", "image_url": {"url": reference_resolver(item.image)}}
            for item in references
        ]
    if payload.seed > 0 and "seed" in parameters:
        body["seed"] = payload.seed
    return body


def build_openrouter_image_request_plan(
    model_id: str,
    width: int,
    height: int,
    capability: dict[str, Any] | None = None,
    *,
    resolution_tier: str = "hd",
) -> dict[str, Any]:
    """Build provider-specific image parameters from application resolution policy."""

    orientation = requested_orientation(int(width or 1024), int(height or 1024))
    aspect_ratio = openrouter_ratio_size(width, height)
    supported_resolutions = openrouter_descriptor_values(capability, "resolution")
    supported_aspects = openrouter_descriptor_values(capability, "aspect_ratio")
    normalized_resolution = {"sd": "512", "hd": "1K", "full_hd": "2K"}.get(str(resolution_tier), "1K")
    if supported_resolutions and normalized_resolution not in supported_resolutions:
        normalized_resolution = ""
    if model_id.startswith("openai/"):
        mapped = {
            "square": (1024, 1024, "1024x1024"),
            "horizontal": (1536, 1024, "1536x1024"),
            "vertical": (1024, 1536, "1024x1536"),
        }[orientation]
        return {
            "size": mapped[2],
            "billing_width": mapped[0],
            "billing_height": mapped[1],
            "strategy": "openai_supported_size",
        }
    if model_id.startswith("recraft/"):
        mapped = {
            "square": (1024, 1024, "1024x1024"),
            "horizontal": (1536, 1024, "1536x1024"),
            "vertical": (1024, 1536, "1024x1536"),
        }[orientation]
        return {
            "size": mapped[2],
            "billing_width": mapped[0],
            "billing_height": mapped[1],
            "strategy": "recraft_safe_size",
        }
    if model_id.startswith("sourceful/"):
        ratio = openrouter_ratio_size(width, height)
        return {
            "size": ratio,
            "resolution": normalized_resolution or None,
            "billing_width": int(width or 1024),
            "billing_height": int(height or 1024),
            "strategy": "sourceful_resolution_ratio",
        }
    if model_id.startswith("google/") and capability is None:
        return {
            "aspect_ratio": aspect_ratio,
            "resolution": normalized_resolution or "1K",
            "billing_width": int(width or 1024),
            "billing_height": int(height or 1024),
            "strategy": "google_normalized_aspect_ratio",
        }
    if supported_aspects or supported_resolutions:
        return {
            "aspect_ratio": aspect_ratio if not supported_aspects or aspect_ratio in supported_aspects else None,
            "resolution": normalized_resolution or None,
            "billing_width": int(width or 1024),
            "billing_height": int(height or 1024),
            "strategy": "openrouter_capability_descriptors",
        }
    return {
        "size": f"{int(width or 1024)}x{int(height or 1024)}",
        "billing_width": int(width or 1024),
        "billing_height": int(height or 1024),
        "strategy": "requested_size",
    }
