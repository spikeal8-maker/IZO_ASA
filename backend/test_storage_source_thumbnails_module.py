"""Source thumbnail decoding and encoding are deterministic and bounded."""

from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image

from app.storage.source_thumbnails import (
    SourceThumbnailRuntime,
    open_source_image,
    save_source_thumbnail,
)


def _runtime(media: Path, *, max_side: int = 32) -> SourceThumbnailRuntime:
    def resolve_local_media(url: str) -> Path | None:
        prefix = "/api/media/"
        if not url.startswith(prefix):
            return None
        candidate = media / url[len(prefix):].split("?", 1)[0]
        return candidate if candidate.is_file() else None

    return SourceThumbnailRuntime(
        media_dir=media,
        resolve_local_media=resolve_local_media,
        max_side=max_side,
        webp_quality=76,
    )


def test_data_url_thumbnail_applies_exif_orientation_and_webp_bounds(tmp_path: Path):
    media = tmp_path / "media"
    media.mkdir()
    buffer = io.BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (80, 40), "purple").save(buffer, "JPEG", exif=exif)
    data_url = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")

    result = save_source_thumbnail(_runtime(media), data_url, "image-id", 2)

    assert result is not None
    path, width, height, byte_size = result
    assert path.parent == media
    assert path.name.startswith("image-id_source2_")
    assert path.suffix == ".webp"
    assert (width, height) == (16, 32)
    assert byte_size == path.stat().st_size > 0
    with Image.open(path) as encoded:
        assert encoded.format == "WEBP"
        assert encoded.mode == "RGB"
        assert encoded.size == (16, 32)


def test_local_media_and_invalid_sources_are_handled_without_artifacts(tmp_path: Path):
    media = tmp_path / "media"
    media.mkdir()
    local = media / "local.png"
    Image.new("RGBA", (12, 20), "green").save(local, "PNG")
    broken = media / "broken.png"
    broken.write_bytes(b"not-an-image")
    runtime = _runtime(media)

    opened = open_source_image(runtime, "/api/media/local.png?userId=owner")
    assert opened is not None
    with opened:
        assert opened.size == (12, 20)
    assert open_source_image(runtime, None) is None
    assert open_source_image(runtime, "data:image/png;base64,not-base64") is None
    assert open_source_image(runtime, "/api/media/missing.png") is None
    assert save_source_thumbnail(runtime, "/api/media/broken.png", "broken", 1) is None
    assert list(media.glob("broken_source*.webp")) == []
