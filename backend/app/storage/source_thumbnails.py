"""Decode source images and create bounded WEBP thumbnails."""

from __future__ import annotations

import base64
import io
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps


SourceThumb = tuple[Path, int, int, int]


@dataclass(frozen=True)
class SourceThumbnailRuntime:
    media_dir: Path
    resolve_local_media: Callable[[str], Path | None]
    max_side: int
    webp_quality: int


def open_source_image(runtime: SourceThumbnailRuntime, source_value: str | None) -> Image.Image | None:
    if not source_value:
        return None
    if source_value.startswith("data:image"):
        try:
            _header, encoded = source_value.split(",", 1)
            return Image.open(io.BytesIO(base64.b64decode(encoded)))
        except Exception:
            return None
    path = runtime.resolve_local_media(source_value)
    if path and path.exists():
        try:
            return Image.open(path)
        except Exception:
            return None
    return None


def save_source_thumbnail(
    runtime: SourceThumbnailRuntime,
    source_value: str | None,
    image_id: str,
    slot_index: int,
) -> SourceThumb | None:
    opened = open_source_image(runtime, source_value)
    if opened is None:
        return None
    try:
        with opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail((runtime.max_side, runtime.max_side), Image.Resampling.LANCZOS)
            target = runtime.media_dir / f"{image_id}_source{slot_index}_{uuid.uuid4().hex[:10]}.webp"
            image.save(target, "WEBP", quality=runtime.webp_quality, method=6)
            return target, image.width, image.height, target.stat().st_size
    except Exception:
        return None
