"""Bounded ComfyUI reference-image sizing without accidental upscaling."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Callable
from uuid import uuid4

from PIL import Image, ImageOps


ALIGNMENT = 16


def fit_reference_size(
    source_size: tuple[int, int],
    *,
    target_box: tuple[int, int],
    max_side: int,
    max_megapixels: float | None = None,
) -> tuple[int, int]:
    """Fit one reference inside every limit while preserving its aspect ratio.

    The scale is never greater than one. Dimensions are rounded down to the
    model alignment so the megapixel ceiling cannot be exceeded by rounding.
    """

    source_w, source_h = source_size
    if source_w <= 0 or source_h <= 0:
        return (1024, 1024)
    box_w = max(ALIGNMENT, int(target_box[0] or max_side))
    box_h = max(ALIGNMENT, int(target_box[1] or max_side))
    scale = min(1.0, box_w / source_w, box_h / source_h, max_side / max(source_size))
    if max_megapixels is not None and max_megapixels > 0:
        pixel_limit = max_megapixels * 1_000_000
        scale = min(scale, math.sqrt(pixel_limit / (source_w * source_h)))
    width = max(ALIGNMENT, int(source_w * scale) // ALIGNMENT * ALIGNMENT)
    height = max(ALIGNMENT, int(source_h * scale) // ALIGNMENT * ALIGNMENT)
    return width, height


def image_megapixels(size: tuple[int, int]) -> float:
    width, height = size
    return max(0.001, (max(1, width) * max(1, height)) / 1_000_000)


def outpaint_padding(raw: dict[str, object]) -> dict[str, int]:
    padding: dict[str, int] = {}
    for key in ("left", "right", "top", "bottom"):
        try:
            value = int(raw.get(key, 0))  # type: ignore[arg-type]
        except Exception:
            value = 0
        padding[key] = max(0, min(8192, value))
    return padding


def _safe_int(raw: dict[str, object], key: str, default: int = 0) -> int:
    try:
        value = raw.get(key, default)
        return default if isinstance(value, bool) else int(value)  # type: ignore[arg-type]
    except Exception:
        return default


def outpaint_placement(
    raw: dict[str, object],
    *,
    target_size: tuple[int, int],
    default_frame_size: tuple[int, int],
) -> dict[str, int] | None:
    if not all(key in raw for key in ("sourceX", "sourceY", "sourceW", "sourceH")):
        return None
    target_w, target_h = target_size
    frame_w = max(1, _safe_int(raw, "frameW", default_frame_size[0]))
    frame_h = max(1, _safe_int(raw, "frameH", default_frame_size[1]))
    source_w = max(1, _safe_int(raw, "sourceW", frame_w))
    source_h = max(1, _safe_int(raw, "sourceH", frame_h))
    scale_x, scale_y = target_w / frame_w, target_h / frame_h
    return {
        "x": int(round(_safe_int(raw, "sourceX") * scale_x)),
        "y": int(round(_safe_int(raw, "sourceY") * scale_y)),
        "w": max(1, int(round(source_w * scale_x))),
        "h": max(1, int(round(source_h * scale_y))),
    }


def prepare_reference_image(
    image_path: Path | None,
    *,
    output_directory: Path,
    prefix: str,
    target_box: tuple[int, int],
    max_side: int,
    minimum_side: int,
    max_megapixels: float | None = None,
    log: Callable[[str], None] | None = None,
) -> Path | None:
    """Resize one reference without enlarging it; preserve the original on errors."""

    if not image_path or not image_path.exists():
        return image_path
    emit = log or (lambda _message: None)
    try:
        with Image.open(image_path) as opened:
            image = ImageOps.exif_transpose(opened)
            limit = max(minimum_side, max_side)
            box = tuple(max(minimum_side, min(limit, int(value or limit))) for value in target_box)
            target_size = fit_reference_size(
                image.size,
                target_box=box,
                max_side=limit,
                max_megapixels=max_megapixels,
            )
            if image.size == target_size:
                return image_path
            resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
            resized = image.resize(target_size, resample)
            if resized.mode not in ("RGB", "RGBA"):
                resized = resized.convert("RGBA" if "A" in resized.getbands() else "RGB")
            output = output_directory / f"{prefix}_{uuid4().hex}_comfy.png"
            resized.save(output, "PNG", optimize=True)
            emit(
                f"comfyui input resized {image_path.name}: "
                f"{image.size[0]}x{image.size[1]} -> {target_size[0]}x{target_size[1]}"
            )
            return output
    except Exception as exc:
        emit(f"comfyui input resize skipped {image_path.name}: {type(exc).__name__}")
        return image_path


def prepare_mask_image(
    mask_path: Path | None,
    reference_path: Path | None,
    *,
    output_directory: Path,
    prefix: str,
    log: Callable[[str], None] | None = None,
) -> Path | None:
    """Force an inpaint/outpaint mask to the exact prepared-image dimensions."""

    if not mask_path or not mask_path.exists() or not reference_path or not reference_path.exists():
        return mask_path
    emit = log or (lambda _message: None)
    try:
        with Image.open(reference_path) as reference, Image.open(mask_path) as opened_mask:
            target_size = ImageOps.exif_transpose(reference).size
            mask = ImageOps.exif_transpose(opened_mask).convert("RGB")
            if mask.size == target_size:
                return mask_path
            resample = Image.Resampling.NEAREST if hasattr(Image, "Resampling") else Image.NEAREST
            resized = mask.resize(target_size, resample)
            output = output_directory / f"{prefix}_{uuid4().hex}_comfy_mask.png"
            resized.save(output, "PNG", optimize=True)
            emit(
                f"comfyui mask aligned {mask_path.name}: "
                f"{mask.size[0]}x{mask.size[1]} -> {target_size[0]}x{target_size[1]}"
            )
            return output
    except Exception as exc:
        emit(f"comfyui mask alignment skipped {mask_path.name}: {type(exc).__name__}")
        return mask_path
