from __future__ import annotations

from typing import Any, Iterable


IMAGE_RESOLUTIONS: tuple[dict[str, Any], ...] = (
    {"id": "sq-sd", "format": "square", "tier": "sd", "width": 704, "height": 704},
    {"id": "sq-hd", "format": "square", "tier": "hd", "width": 1024, "height": 1024},
    {"id": "sq-fhd", "format": "square", "tier": "full_hd", "width": 1408, "height": 1408},
    {"id": "v-sd", "format": "portrait", "tier": "sd", "width": 576, "height": 1024},
    {"id": "v-hd", "format": "portrait", "tier": "hd", "width": 720, "height": 1280},
    {"id": "v-fhd", "format": "portrait", "tier": "full_hd", "width": 1008, "height": 1792},
    {"id": "h-sd", "format": "wide", "tier": "sd", "width": 1024, "height": 576},
    {"id": "h-hd", "format": "wide", "tier": "hd", "width": 1280, "height": 720},
    {"id": "h-fhd", "format": "wide", "tier": "full_hd", "width": 1792, "height": 1008},
    {"id": "p-sd", "format": "photo", "tier": "sd", "width": 960, "height": 640},
    {"id": "p-hd", "format": "photo", "tier": "hd", "width": 1152, "height": 768},
    {"id": "p-fhd", "format": "photo", "tier": "full_hd", "width": 1728, "height": 1152},
)

RESOLUTION_BY_ID = {item["id"]: item for item in IMAGE_RESOLUTIONS}
RESOLUTION_ID_BY_SIZE = {(item["width"], item["height"]): item["id"] for item in IMAGE_RESOLUTIONS}
CONFIG_UI_RESOLUTION_IDS = tuple(item["id"] for item in IMAGE_RESOLUTIONS)
LEGACY_RESOLUTION_IDS = {
    "sq-1024": "sq-hd", "h-1280": "h-hd", "v-720": "v-hd", "h-1536": "p-hd",
    "v-1024": "v-fhd", "h-1920": "h-fhd", "v-1088": "v-fhd",
}


def normalize_resolution_id(value: Any) -> str | None:
    resolution_id = LEGACY_RESOLUTION_IDS.get(str(value), str(value))
    return resolution_id if resolution_id in RESOLUTION_BY_ID else None


def normalize_resolution_ids(values: Iterable[Any] | None, fallback: Iterable[str] = ()) -> list[str]:
    result: list[str] = []
    for value in values or ():
        resolution_id = normalize_resolution_id(value)
        if resolution_id and resolution_id not in result:
            result.append(resolution_id)
    return result or list(fallback)


def resolution_id_for_size(width: int, height: int) -> str | None:
    return RESOLUTION_ID_BY_SIZE.get((int(width), int(height)))


def _descriptor_values(capability: dict[str, Any], parameter: str) -> list[str]:
    descriptors = capability.get("parameterDescriptors")
    if not isinstance(descriptors, dict):
        return []
    descriptor = descriptors.get(parameter)
    if not isinstance(descriptor, dict):
        return []
    values = descriptor.get("values") or descriptor.get("enum") or []
    return [str(value) for value in values] if isinstance(values, list) else []


def supported_resolution_ids_from_capability(capability: dict[str, Any] | None) -> list[str]:
    if not capability:
        return []
    model_id = str(capability.get("id") or "").lower()
    aspects = set(_descriptor_values(capability, "aspect_ratio"))
    sizes = set(_descriptor_values(capability, "size"))
    tiers = set(_descriptor_values(capability, "resolution"))
    supported_parameters = set(str(value) for value in capability.get("supportedParameters") or [])

    if sizes:
        exact_size_map = {
            "1024x1024": "sq-hd", "1024×1024": "sq-hd",
            "1536x1024": "p-fhd", "1536×1024": "p-fhd",
        }
        exact = [resolution_id for size, resolution_id in exact_size_map.items() if size in sizes]
        if exact:
            return exact

    # Several OpenRouter providers expose their accepted sizes through the
    # generation endpoint but omit aspect/size descriptors from the catalog.
    # Keep these rules aligned with openrouter_image_request_plan().
    if not aspects:
        if model_id.startswith("black-forest-labs/"):
            return [item["id"] for item in IMAGE_RESOLUTIONS]
        if model_id.startswith(("openai/", "recraft/")):
            return ["sq-hd", "v-fhd", "p-fhd"]
        if model_id.startswith("sourceful/"):
            allowed_tiers = {"hd", "full_hd"} if tiers else {"hd"}
            return [item["id"] for item in IMAGE_RESOLUTIONS if item["tier"] in allowed_tiers]

    format_aspects = {"square": "1:1", "portrait": "9:16", "wide": "16:9", "photo": "3:2"}
    tier_values = {"sd": {"512", "0.5K"}, "hd": {"1K", "1024"}, "full_hd": {"2K", "2048"}}
    has_aspect_control = "aspect_ratio" in supported_parameters or bool(aspects)
    has_resolution_control = "resolution" in supported_parameters or bool(tiers)
    result: list[str] = []
    for item in IMAGE_RESOLUTIONS:
        aspect_ok = (not has_aspect_control) or format_aspects[item["format"]] in aspects
        tier_ok = (not has_resolution_control and item["tier"] == "hd") or bool(tier_values[item["tier"]] & tiers)
        if aspect_ok and tier_ok:
            result.append(item["id"])
    return result or [item["id"] for item in IMAGE_RESOLUTIONS if item["tier"] == "hd"]
