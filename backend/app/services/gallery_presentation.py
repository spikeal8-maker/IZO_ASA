"""Pure gallery presentation helpers shared by item payload builders."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Any


MODE_LABELS = {
    "text_to_image": "По тексту",
    "image_to_image": "По фото",
    "edit": "Сборка",
    "paint": "Редактор",
    "inpaint": "Инпейнт",
    "outpaint": "Аутпейнт",
    "try_on": "Примерка",
    "texture_transfer": "Перенос текстуры",
    "remove_background": "Удаление фона",
    "faceswap": "Лицо",
    "face": "Лицо",
    "face_swap": "Лицо",
    "drawing": "Редактор",
    "editor": "Сборка",
}


def gallery_aspect_ratio(width: int | None, height: int | None) -> str | None:
    if not width or not height:
        return None
    gcd = math.gcd(int(width), int(height))
    if gcd <= 0:
        return None
    return f"{int(width) // gcd}:{int(height) // gcd}"


def gallery_mode_label(mode: str | None) -> str:
    return MODE_LABELS.get(str(mode or "").strip(), str(mode or "По тексту"))


def gallery_source_ids(settings: Mapping[str, Any]) -> list[str]:
    raw = settings.get("sourceImageIds") or settings.get("source_image_ids") or settings.get("sourceIds") or []
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw[:4] if str(item or "").strip()]


def gallery_model_info(
    settings: Mapping[str, Any],
    provider: str | None,
    *,
    price_catalog: Mapping[str, Any],
    release_years: Mapping[str, str],
    model_display_name: Callable[[Any], str],
) -> dict[str, str]:
    raw = str(settings.get("modelProfile") or settings.get("openrouterModel") or provider or "").strip()
    billing = settings.get("openrouterBilling") if isinstance(settings.get("openrouterBilling"), dict) else {}
    catalog_item = price_catalog.get(raw)
    short_name = str(billing.get("modelName") or getattr(catalog_item, "name", None) or model_display_name(raw))
    maker = str(billing.get("modelProvider") or getattr(catalog_item, "provider", None) or "")
    release = release_years.get(raw) or ("2026" if raw else "")
    if not raw or raw == "comfyui" or "local_flux" in raw.lower() or "klein" in raw.lower():
        short_name = "ИЗО Base"
        maker = "ИЗО / FLUX.2 Klein"
        release = "2026"
    full_parts = [short_name]
    if maker:
        full_parts.append(maker)
    if release:
        full_parts.append(f"выпуск: {release}")
    return {
        "shortName": short_name,
        "fullName": " · ".join(full_parts),
        "providerName": maker,
        "release": release,
    }
