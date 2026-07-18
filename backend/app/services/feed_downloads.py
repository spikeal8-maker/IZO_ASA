"""Branded, broadly compatible downloads for public feed publications."""

from __future__ import annotations

import io
import os
import re
import threading
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


DOWNLOAD_FORMATS = {"jpeg", "png"}
BRAND_NAME = "ИЗО АСА"
BRAND_DOMAIN = "izo.alikinas.ru"
WATERMARK_VERSION = "v2"
LEGACY_WATERMARK_VERSIONS = ("v1",)


class FeedDownloadError(ValueError):
    pass


_VIDEO_DOWNLOAD_LOCK = threading.Lock()


def video_download_name(publication_id: str, *, version: str | None = None) -> str:
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", publication_id)
    selected_version = str(version or WATERMARK_VERSION)
    return f"feed/{safe_id}_video_download_{selected_version}.mp4"


def video_download_names(publication_id: str) -> tuple[str, ...]:
    return (
        video_download_name(publication_id),
        *(video_download_name(publication_id, version=version) for version in LEGACY_WATERMARK_VERSIONS),
    )


def normalize_download_format(value: str | None) -> str:
    selected = str(value or "jpeg").strip().lower()
    if selected == "jpg":
        selected = "jpeg"
    if selected not in DOWNLOAD_FORMATS:
        raise FeedDownloadError("Unsupported download format")
    return selected


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    names = (
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "arialbd.ttf" if bold else "arial.ttf",
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_brand_mark(draw: ImageDraw.ImageDraw, left: int, top: int, size: int) -> None:
    acid = (214, 239, 34, 235)
    width = max(2, size // 12)
    draw.rounded_rectangle(
        (left, top, left + size, top + size),
        radius=max(3, size // 5),
        outline=acid,
        width=width,
    )
    inset = max(5, size // 4)
    inner = (left + inset, top + inset, left + size - inset, top + size - inset)
    draw.rounded_rectangle(inner, radius=max(2, size // 10), outline=acid, width=width)
    spacing = max(5, size // 5)
    for offset in range(-size, size * 2, spacing):
        x1 = max(inner[0], inner[0] + offset)
        y1 = max(inner[1], inner[1] - offset)
        x2 = min(inner[2], inner[2] + offset)
        y2 = min(inner[3], inner[3] - offset)
        if x1 <= x2 and y1 <= y2:
            draw.line((x1, y1, x2, y2), fill=acid, width=max(1, width - 1))


def render_video_watermark_overlay(
    width: int,
    height: int,
    *,
    brand_name: str = BRAND_NAME,
    domain: str = BRAND_DOMAIN,
) -> bytes:
    short_side = max(1, min(int(width or 0), int(height or 0)))
    mark_size = max(28, min(64, round(short_side * 0.065)))
    title_font = _font(max(14, round(mark_size * 0.38)), bold=True)
    domain_font = _font(max(12, round(mark_size * 0.31)))
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
    title_box = measure.textbbox((0, 0), brand_name, font=title_font)
    domain_box = measure.textbbox((0, 0), domain, font=domain_font)
    text_width = max(title_box[2] - title_box[0], domain_box[2] - domain_box[0])
    gap = max(7, mark_size // 5)
    pad_x = max(8, mark_size // 5)
    pad_y = max(7, mark_size // 6)
    overlay_width = mark_size + gap + text_width + pad_x * 2
    overlay_height = max(
        mark_size,
        (title_box[3] - title_box[1]) + (domain_box[3] - domain_box[1]) + 4,
    ) + pad_y * 2
    overlay = Image.new("RGBA", (overlay_width, overlay_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle(
        (0, 0, overlay_width - 1, overlay_height - 1),
        radius=max(8, overlay_height // 5),
        fill=(5, 8, 6, 150),
        outline=(255, 255, 255, 42),
        width=1,
    )
    mark_left = pad_x
    mark_top = (overlay_height - mark_size) // 2
    _draw_brand_mark(draw, mark_left, mark_top, mark_size)
    text_left = mark_left + mark_size + gap
    title_top = pad_y
    draw.text((text_left + 1, title_top + 1), brand_name, font=title_font, fill=(0, 0, 0, 190))
    draw.text((text_left, title_top), brand_name, font=title_font, fill=(250, 252, 247, 245))
    domain_top = title_top + (title_box[3] - title_box[1]) + 3
    draw.text((text_left, domain_top), domain, font=domain_font, fill=(218, 225, 214, 238))
    output = io.BytesIO()
    overlay.save(output, "PNG", optimize=True)
    return output.getvalue()


def ensure_video_download(
    publication_id: str,
    source_path: Path,
    *,
    media_dir: Path,
    width: int,
    height: int,
    run_ffmpeg: Callable[..., None],
) -> Path:
    target_path = media_dir / video_download_name(publication_id)
    with _VIDEO_DOWNLOAD_LOCK:
        for legacy_version in LEGACY_WATERMARK_VERSIONS:
            (media_dir / video_download_name(publication_id, version=legacy_version)).unlink(missing_ok=True)
        if target_path.is_file() and target_path.stat().st_size > 16:
            return target_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        overlay_path = target_path.with_name(f"{target_path.stem}.watermark.part.png")
        temporary_path = target_path.with_name(f"{target_path.stem}.part.mp4")
        overlay_path.unlink(missing_ok=True)
        temporary_path.unlink(missing_ok=True)
        try:
            overlay_path.write_bytes(render_video_watermark_overlay(width, height))
            run_ffmpeg(
                [
                    "-i", str(source_path), "-loop", "1", "-i", str(overlay_path),
                    "-filter_complex",
                    "[0:v][1:v]overlay=main_w-overlay_w-max(12\\,main_w*0.018):"
                    "main_h-overlay_h-max(12\\,main_h*0.018):repeatlast=1:shortest=1[v]",
                    "-map", "[v]", "-map", "0:a?", "-sn", "-dn",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-pix_fmt", "yuv420p", "-threads", "1",
                    "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
                    "-shortest", str(temporary_path),
                ],
                timeout=300,
            )
            if not temporary_path.is_file() or temporary_path.stat().st_size <= 16:
                raise RuntimeError("Branded feed video download is empty")
            os.replace(temporary_path, target_path)
            return target_path
        except Exception:
            target_path.unlink(missing_ok=True)
            temporary_path.unlink(missing_ok=True)
            raise
        finally:
            overlay_path.unlink(missing_ok=True)


def render_feed_download(
    source_path: Path,
    *,
    output_format: str = "jpeg",
    brand_name: str = BRAND_NAME,
    domain: str = BRAND_DOMAIN,
) -> bytes:
    selected = normalize_download_format(output_format)
    with Image.open(source_path) as opened:
        source = ImageOps.exif_transpose(opened)
        image = source.convert("RGBA")

    short_side = max(1, min(image.size))
    margin = max(10, round(short_side * 0.018))
    mark_size = max(28, min(58, round(short_side * 0.055)))
    title_font = _font(max(14, round(mark_size * 0.38)), bold=True)
    domain_font = _font(max(12, round(mark_size * 0.31)))
    measure = ImageDraw.Draw(image)
    title_box = measure.textbbox((0, 0), brand_name, font=title_font)
    domain_box = measure.textbbox((0, 0), domain, font=domain_font)
    text_width = max(title_box[2] - title_box[0], domain_box[2] - domain_box[0])
    gap = max(7, mark_size // 5)
    pad_x = max(8, mark_size // 5)
    pad_y = max(7, mark_size // 6)
    block_width = mark_size + gap + text_width + pad_x * 2
    block_height = max(mark_size, (title_box[3] - title_box[1]) + (domain_box[3] - domain_box[1]) + 4) + pad_y * 2
    left = max(margin, image.width - margin - block_width)
    top = max(margin, image.height - margin - block_height)

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle(
        (left, top, left + block_width, top + block_height),
        radius=max(8, block_height // 5),
        fill=(5, 8, 6, 150),
        outline=(255, 255, 255, 42),
        width=1,
    )
    mark_left = left + pad_x
    mark_top = top + (block_height - mark_size) // 2
    _draw_brand_mark(draw, mark_left, mark_top, mark_size)
    text_left = mark_left + mark_size + gap
    title_top = top + pad_y
    draw.text((text_left + 1, title_top + 1), brand_name, font=title_font, fill=(0, 0, 0, 190))
    draw.text((text_left, title_top), brand_name, font=title_font, fill=(250, 252, 247, 245))
    domain_top = title_top + (title_box[3] - title_box[1]) + 3
    draw.text((text_left, domain_top), domain, font=domain_font, fill=(218, 225, 214, 238))
    branded = Image.alpha_composite(image, overlay)

    output = io.BytesIO()
    if selected == "png":
        branded.save(output, "PNG", optimize=True)
    else:
        if branded.getextrema()[3][0] < 255:
            background = Image.new("RGB", branded.size, "white")
            background.paste(branded, mask=branded.getchannel("A"))
            export = background
        else:
            export = branded.convert("RGB")
        export.save(output, "JPEG", quality=92, optimize=True, progressive=True, subsampling=0)
    return output.getvalue()
