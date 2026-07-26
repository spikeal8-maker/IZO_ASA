"""Provider-native image uploads for social publications."""

from __future__ import annotations

from io import BytesIO
from typing import Any, Awaitable, Callable

import httpx
from PIL import Image


async def _jpeg_from_url(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
    try:
        with Image.open(BytesIO(response.content)) as image:
            output = BytesIO()
            image.convert("RGB").save(output, format="JPEG", quality=92, optimize=True)
            return output.getvalue()
    except Exception as exc:
        raise RuntimeError("Social image conversion failed.") from exc


async def send_telegram_photo_url(
    *, token: str, target_id: str, caption: str, media_url: str
) -> dict[str, Any]:
    image = await _jpeg_from_url(media_url)
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data={"chat_id": target_id, "caption": caption},
                files={"photo": ("publication.jpg", image, "image/jpeg")},
            )
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError("Telegram image upload failed.") from exc
    if response.status_code != 200 or not isinstance(body, dict) or not body.get("ok"):
        description = str(body.get("description") or "request rejected")[:180] if isinstance(body, dict) else "request rejected"
        raise RuntimeError(f"Telegram sendPhoto failed: {description}")
    return body


async def publish_vk_wall_image(
    *,
    vk_api: Callable[..., Awaitable[dict[str, Any]]],
    token: str,
    group_id: str,
    message: str,
    media_url: str,
) -> dict[str, Any]:
    upload_server = await vk_api(
        token=token, method="photos.getWallUploadServer", params={"group_id": group_id}
    )
    upload_url = str((upload_server.get("response") or {}).get("upload_url") or "")
    if not upload_url.startswith("https://"):
        raise RuntimeError("VK did not return a wall photo upload URL.")
    image = await _jpeg_from_url(media_url)
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            uploaded = await client.post(
                upload_url, files={"photo": ("publication.jpg", image, "image/jpeg")}
            )
        upload_body = uploaded.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError("VK photo upload failed.") from exc
    saved = await vk_api(
        token=token, method="photos.saveWallPhoto",
        params={"group_id": group_id, "server": upload_body.get("server"),
                "photo": upload_body.get("photo"), "hash": upload_body.get("hash")},
    )
    photos = saved.get("response") if isinstance(saved.get("response"), list) else []
    photo = photos[0] if photos and isinstance(photos[0], dict) else {}
    owner_id, photo_id = photo.get("owner_id"), photo.get("id")
    if owner_id is None or photo_id is None:
        raise RuntimeError("VK did not save the uploaded wall photo.")
    return await vk_api(
        token=token, method="wall.post",
        params={"owner_id": f"-{group_id}", "from_group": 1, "message": message,
                "attachments": f"photo{owner_id}_{photo_id}"},
    )
