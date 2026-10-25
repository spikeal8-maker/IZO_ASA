"""Synthetic runtime compatibility contracts for Pillow 13 (#233).

All input images are manufactured in memory; all outputs use pytest tmp_path.
The live gallery, provider and user databases are never accessed.
"""

from __future__ import annotations

import io

from PIL import Image, __version__ as pillow_version

import main


def test_exact_pillow_runtime_is_pinned() -> None:
    assert pillow_version == "13.0.0"


def test_avatar_png_is_compressed_as_webp_without_external_media() -> None:
    payload = io.BytesIO()
    Image.new("RGB", (40, 24), (11, 77, 123)).save(payload, "PNG")
    encoded = main.compress_avatar_image(payload.getvalue(), "image/png")
    with Image.open(io.BytesIO(encoded)) as result:
        result.load()
        assert result.format == "WEBP"
        assert result.size == (main.AVATAR_OUTPUT_SIZE, main.AVATAR_OUTPUT_SIZE)


def test_gallery_png_preconverts_32bit_i_mode(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "MEDIA", tmp_path)
    source = Image.new("I", (12, 7), 1024)
    output = main.save_gallery_original(source, "synthetic-i-mode")
    assert output.parent == tmp_path
    with Image.open(output) as result:
        result.load()
        assert result.format == "PNG"
        assert result.mode == "RGB"
        assert result.size == (12, 7)


def test_gallery_corrects_exif_orientation_before_saving(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "MEDIA", tmp_path)
    exif = Image.Exif()
    exif[274] = 6  # Orientation: rotate 90 degrees clockwise.
    payload = io.BytesIO()
    Image.new("RGB", (30, 16), (160, 70, 20)).save(payload, "JPEG", exif=exif)
    payload.seek(0)

    with Image.open(payload) as original:
        assert original.getexif().get(274) == 6
        saved = main.save_gallery_original(original, "synthetic-exif")

    with Image.open(saved) as result:
        result.load()
        assert result.format == "PNG"
        assert result.size == (16, 30)


def test_thumbnail_converts_rgba_png_to_decodable_webp(tmp_path) -> None:
    source = tmp_path / "synthetic-source.png"
    Image.new("RGBA", (1024, 512), (15, 35, 55, 127)).save(source, "PNG")
    thumb = main.create_thumbnail(source)
    assert thumb.parent == tmp_path
    assert thumb.name == "synthetic-source_thumb.webp"
    with Image.open(thumb) as result:
        result.load()
        assert result.format == "WEBP"
        assert result.size == (512, 256)
        assert result.mode in ("RGB", "RGBA")
