"""Provider-native media uploads for social publications."""

from __future__ import annotations

from io import BytesIO
import json
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


async def _media_from_url(url: str, *, timeout: float = 120) -> bytes:
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content
    except httpx.HTTPError as exc:
        raise RuntimeError("Social media download failed.") from exc


async def send_telegram_photo_url(
    *, token: str, target_id: str, caption: str, media_url: str,
    reply_markup: str | None = None,
) -> dict[str, Any]:
    image = await _jpeg_from_url(media_url)
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data={"chat_id": target_id, "caption": caption, **({"reply_markup": reply_markup} if reply_markup else {})},
                files={"photo": ("publication.jpg", image, "image/jpeg")},
            )
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError("Telegram image upload failed.") from exc
    if response.status_code != 200 or not isinstance(body, dict) or not body.get("ok"):
        description = str(body.get("description") or "request rejected")[:180] if isinstance(body, dict) else "request rejected"
        raise RuntimeError(f"Telegram sendPhoto failed: {description}")
    return body


async def send_telegram_video_url(
    *, token: str, target_id: str, caption: str, media_url: str,
    reply_markup: str | None = None,
) -> dict[str, Any]:
    video = await _media_from_url(media_url, timeout=180)
    try:
        async with httpx.AsyncClient(timeout=240) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{token}/sendVideo",
                data={"chat_id": target_id, "caption": caption, "supports_streaming": "true",
                      **({"reply_markup": reply_markup} if reply_markup else {})},
                files={"video": ("publication.mp4", video, "video/mp4")},
            )
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError("Telegram video upload failed.") from exc
    if response.status_code != 200 or not isinstance(body, dict) or not body.get("ok"):
        description = str(body.get("description") or "request rejected")[:180] if isinstance(body, dict) else "request rejected"
        raise RuntimeError(f"Telegram sendVideo failed: {description}")
    return body


async def publish_max_video(
    *, max_api: Callable[..., Awaitable[dict[str, Any]]], token: str,
    target_id: str, message: str, media_url: str, feed_url: str,
    api_base_url: str, verify: Any = True,
) -> dict[str, Any]:
    upload = await max_api(
        token=token, base_url=api_base_url, verify=verify, method="POST",
        path="/uploads", params={"type": "video"}, payload=None,
    )
    upload_url = str(upload.get("url") or "")
    token_value = str(upload.get("token") or "")
    if not upload_url.startswith("https://"):
        raise RuntimeError("MAX did not return a video upload URL.")
    video = await _media_from_url(media_url, timeout=180)
    try:
        async with httpx.AsyncClient(timeout=240, verify=verify) as client:
            response = await client.post(
                upload_url, headers={"Authorization": token},
                files={"data": ("publication.mp4", video, "video/mp4")},
            )
        try:
            uploaded = response.json()
        except ValueError:
            # MAX video hosts may acknowledge a successful multipart upload
            # with plain text/retval. The attachment token was already issued
            # by POST /uploads and remains authoritative.
            uploaded = {}
    except httpx.HTTPError as exc:
        raise RuntimeError(f"MAX video upload failed: {type(exc).__name__}.") from exc
    if response.status_code >= 400:
        raise RuntimeError(f"MAX video upload returned HTTP {response.status_code}.")
    token_value = str(uploaded.get("token") or token_value)
    if not token_value:
        raise RuntimeError("MAX video upload did not return an attachment token.")
    return await max_api(
        token=token, base_url=api_base_url, verify=verify, method="POST",
        path="/messages", params={"chat_id": target_id},
        payload={"text": message, "attachments": [
            {"type": "video", "payload": {"token": token_value}},
            {"type": "inline_keyboard", "payload": {"buttons": [[
                {"type": "link", "text": "Открыть ленту", "url": feed_url}
            ]]}},
        ]},
    )


async def publish_vk_wall_image(
    *,
    vk_api: Callable[..., Awaitable[dict[str, Any]]],
    token: str,
    media_token: str,
    group_id: str,
    message: str,
    media_url: str,
) -> dict[str, Any]:
    upload_server = await vk_api(
        token=media_token, method="photos.getWallUploadServer", params={"group_id": group_id}
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
    photo_value = upload_body.get("photo") or upload_body.get("photos_list")
    if not photo_value:
        fields = ", ".join(sorted(str(key) for key in upload_body))[:160]
        raise RuntimeError(f"VK upload response is missing photo data (fields: {fields or 'none'}).")
    saved = await vk_api(
        token=media_token, method="photos.saveWallPhoto",
        params={"group_id": group_id, "server": upload_body.get("server"),
                "photo": photo_value, "hash": upload_body.get("hash")},
    )
    photos = saved.get("response") if isinstance(saved.get("response"), list) else []
    photo = photos[0] if photos and isinstance(photos[0], dict) else {}
    owner_id, photo_id = photo.get("owner_id"), photo.get("id")
    if owner_id is None or photo_id is None:
        raise RuntimeError("VK did not save the uploaded wall photo.")
    result = await vk_api(
        token=token, method="wall.post",
        params={"owner_id": f"-{group_id}", "from_group": 1, "message": message,
                "attachments": f"photo{owner_id}_{photo_id}"},
    )
    result["_media_ref"] = f"photo{owner_id}_{photo_id}"
    return result


async def publish_vk_wall_video(
    *, vk_api: Callable[..., Awaitable[dict[str, Any]]], token: str,
    media_token: str, group_id: str, message: str, media_url: str,
) -> dict[str, Any]:
    saved = await vk_api(
        token=media_token, method="video.save",
        params={"group_id": group_id, "name": message.splitlines()[0][:128],
                "description": message[:5000], "wallpost": 0},
    )
    video_info = saved.get("response") if isinstance(saved.get("response"), dict) else {}
    upload_url = str(video_info.get("upload_url") or "")
    owner_id, video_id = video_info.get("owner_id"), video_info.get("video_id")
    if not upload_url.startswith("https://") or owner_id is None or video_id is None:
        raise RuntimeError("VK did not return a video upload URL.")
    video = await _media_from_url(media_url, timeout=180)
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            uploaded = await client.post(
                upload_url,
                files={"video_file": ("publication.mp4", video, "video/mp4")},
            )
        upload_body = uploaded.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError("VK video upload failed.") from exc
    if uploaded.status_code >= 400 or upload_body.get("error"):
        raise RuntimeError(f"VK video upload was rejected: {str(upload_body.get('error') or uploaded.status_code)[:180]}")
    result = await vk_api(
        token=token, method="wall.post",
        params={"owner_id": f"-{group_id}", "from_group": 1, "message": message,
                "attachments": f"video{owner_id}_{video_id}"},
    )
    result["_media_ref"] = f"video{owner_id}_{video_id}"
    return result


async def publish_vk_story(
    *, vk_api: Callable[..., Awaitable[dict[str, Any]]], media_token: str,
    group_id: str, media_type: str, media_url: str, feed_url: str,
) -> dict[str, Any]:
    method = "stories.getVideoUploadServer" if media_type == "video" else "stories.getPhotoUploadServer"
    server = await vk_api(
        token=media_token, method=method,
        params={"group_id": group_id, "add_to_news": 1},
    )
    upload_url = str((server.get("response") or {}).get("upload_url") or "")
    if not upload_url.startswith("https://"):
        raise RuntimeError("VK did not return a Stories upload URL.")
    media = await _media_from_url(media_url, timeout=180) if media_type == "video" else await _jpeg_from_url(media_url)
    filename = "story.mp4" if media_type == "video" else "story.jpg"
    content_type = "video/mp4" if media_type == "video" else "image/jpeg"
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(upload_url, files={"file": (filename, media, content_type)})
        uploaded = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError("VK Stories media upload failed.") from exc
    response_body = uploaded.get("response") if isinstance(uploaded.get("response"), dict) else uploaded
    upload_result = response_body.get("upload_result") if isinstance(response_body, dict) else None
    if response.status_code >= 400 or not upload_result:
        raise RuntimeError(f"VK Stories upload was rejected: {str(uploaded)[:180]}")
    save_params = (
        {"upload_results": upload_result}
        if isinstance(upload_result, str)
        else {"upload_results_json": json.dumps([upload_result], ensure_ascii=False)}
    )
    return await vk_api(
        token=media_token, method="stories.save",
        params=save_params,
    )
