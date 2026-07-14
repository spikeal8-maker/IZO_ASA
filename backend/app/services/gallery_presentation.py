"""Pure gallery presentation helpers shared by item payload builders."""

from __future__ import annotations

import math
from collections.abc import Mapping
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
