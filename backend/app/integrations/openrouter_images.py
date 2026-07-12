"""Pure OpenRouter image request planning helpers."""

from __future__ import annotations

import math
from typing import Any


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
