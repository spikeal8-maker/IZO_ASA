"""Normalize generation source inputs and user-facing source role labels."""

from __future__ import annotations

from typing import Any


def source_role_label(role: str | None, slot_index: int, mode: str | None = None) -> str:
    key = str(role or "").strip().lower()
    labels = {
        "base": "Основа",
        "image": "Изображение",
        "reference": "Референс",
        "ref": "Референс",
        "pose": "Поза",
        "face": "Лицо",
        "target": "Основа",
        "source": "Источник",
        "style": "Стиль",
        "clothes": "Одежда",
        "clothing": "Одежда",
        "background": "Фон",
        "mask": "Маска",
        "canvas": "Холст",
    }
    if key in labels:
        return labels[key]
    if slot_index == 1:
        return "Основа"
    if mode == "faceswap" and slot_index == 2:
        return "Лицо"
    if mode == "try_on" and slot_index == 2:
        return "Одежда"
    return f"Исходник {slot_index}"


def generation_source_inputs(request: Any) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    if request.mode == "edit" and request.inputImages:
        for item in sorted(request.inputImages, key=lambda value: value.index or 0):
            if item.image:
                index = int(item.index or len(sources) + 1)
                sources.append(
                    {
                        "slot": index,
                        "role": item.role or ("base" if index == 1 else "reference"),
                        "value": item.image,
                    }
                )
    else:
        if request.inputImage1:
            role = "target" if request.mode == "faceswap" else "base"
            sources.append({"slot": 1, "role": role, "value": request.inputImage1})
        if request.inputImage2:
            role = "reference"
            if request.mode == "faceswap":
                role = "face"
            elif request.mode == "try_on":
                role = "clothes"
            sources.append({"slot": 2, "role": role, "value": request.inputImage2})
    if request.canvas:
        sources.append(
            {
                "slot": max([int(source["slot"]) for source in sources] or [0]) + 1,
                "role": "canvas",
                "value": request.canvas,
            }
        )
    mask_value = request.maskImage or request.outpaintMask
    if mask_value:
        sources.append(
            {
                "slot": max([int(source["slot"]) for source in sources] or [0]) + 1,
                "role": "mask",
                "value": mask_value,
            }
        )
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for source in sources[:8]:
        key = (str(source.get("role") or ""), str(source.get("value") or "")[:500])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped
