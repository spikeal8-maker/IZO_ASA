"""Import-safe feed generation snapshot presentation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


def video_source_history(mode: str | None) -> list[dict[str, Any]]:
    if mode == "image_to_video":
        return [{"kind": "generation_input", "role": "first_frame", "roleLabel": "Исходное изображение"}]
    if mode == "first_last_frame":
        return [
            {"kind": "generation_input", "role": "first_frame", "roleLabel": "Начальный кадр"},
            {"kind": "generation_input", "role": "last_frame", "roleLabel": "Конечный кадр"},
        ]
    if mode == "reference_to_video":
        return [{"kind": "generation_input", "role": "references", "roleLabel": "Референсы"}]
    return []


def feed_generation_snapshot(
    connection: Any,
    image: Any,
    *,
    load_settings: Callable[[Any], Any],
    row_get: Callable[[Any, str], Any],
    model_info: Callable[[Mapping[str, Any], str | None], Any],
    model_display_name: Callable[[Any], str],
    aspect_ratio: Callable[[int, int], str | None],
    public_params: Callable[..., list[dict[str, str]]],
    source_history: Callable[[Any, str], list[dict[str, Any]]],
    token_cost: Callable[[Mapping[str, Any]], int | None],
    media_file_size: Callable[[str | None], int | None],
) -> dict[str, Any]:
    settings = load_settings(row_get(image, "settings_json")) or {}
    if not isinstance(settings, Mapping):
        settings = {}
    width = int(row_get(image, "width") or 0)
    height = int(row_get(image, "height") or 0)
    resolved_model_info = model_info(settings, row_get(image, "provider"))
    return {
        "prompt": str(row_get(image, "prompt_original") or "").strip(),
        "mode": row_get(image, "mode"),
        "provider": row_get(image, "provider"),
        "style": settings.get("styleName") or None,
        "model": model_display_name(settings.get("modelProfile") or row_get(image, "provider")),
        "modelInfo": resolved_model_info,
        "width": width,
        "height": height,
        "aspectRatio": aspect_ratio(width, height),
        "generationParams": public_params(
            image_id=image["id"],
            mode=row_get(image, "mode"),
            provider=row_get(image, "provider"),
            width=width,
            height=height,
            url=row_get(image, "url"),
            created_at=row_get(image, "created_at"),
            settings=settings,
        ),
        "sourceHistory": source_history(connection, image["id"]),
        "tokenCost": token_cost(settings),
        "generationTimeMs": settings.get("generationTimeMs"),
        "fileSizeBytes": media_file_size(row_get(image, "url")),
        "seed": settings.get("seed"),
        "generatedAt": row_get(image, "created_at"),
    }
