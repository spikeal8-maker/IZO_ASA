"""OpenRouter image reference encoding and response loading boundaries."""

from __future__ import annotations

import base64
import io
import mimetypes
from pathlib import Path
from typing import Any, Callable

import httpx
from PIL import Image


def resolve_openrouter_reference_value(
    source: str | None,
    *,
    local_path_resolver: Callable[[str], Path | None],
) -> str:
    """Return a remote/data URL or encode an application-resolved local file."""

    value = (source or "").strip()
    if not value:
        raise RuntimeError("Для режима «По фото» требуется исходное изображение.")
    if value.startswith("data:image/") or value.startswith("https://") or value.startswith("http://"):
        return value
    local_path = local_path_resolver(value)
    if local_path is None:
        raise RuntimeError("Исходное изображение недоступно для OpenRouter.")
    mime = mimetypes.guess_type(local_path.name)[0] or "image/png"
    encoded = base64.b64encode(local_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


async def load_openrouter_response_image(
    image_payload: dict[str, Any],
    *,
    timeout_seconds: float,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Image.Image:
    """Load the legacy OpenRouter b64/data-URL/remote-URL image shapes."""

    b64_value = image_payload.get("b64_json") or image_payload.get("base64") or image_payload.get("image_base64")
    if isinstance(b64_value, str) and b64_value:
        if "," in b64_value and b64_value.split(",", 1)[0].startswith("data:"):
            b64_value = b64_value.split(",", 1)[1]
        return Image.open(io.BytesIO(base64.b64decode(b64_value)))
    url = image_payload.get("url")
    if isinstance(url, str) and url:
        client_options: dict[str, Any] = {
            "timeout": timeout_seconds,
            "follow_redirects": True,
        }
        if transport is not None:
            client_options["transport"] = transport
        async with httpx.AsyncClient(**client_options) as client:
            response = await client.get(url)
            response.raise_for_status()
        return Image.open(io.BytesIO(response.content))
    raise RuntimeError("OpenRouter response не содержит b64_json или url изображения.")
