from __future__ import annotations

from typing import Any, Callable

from ..integrations.openrouter import OpenRouterVideoRequestError, openrouter_video_public_error


def config_viewer_context(
    request: Any,
    *,
    require_user: Callable[[Any], dict[str, Any]],
    connect: Callable[[], Any],
    quota_for_user: Callable[[Any, Any, str], dict[str, Any]],
    storage_state_for_user: Callable[..., Any],
    row_get: Callable[[Any, str], Any],
) -> dict[str, Any]:
    """Resolve private quota data or a zero-quota signed-out catalogue view."""

    try:
        trusted = require_user(request)
    except Exception as exc:
        if int(getattr(exc, "status_code", 0) or 0) != 401:
            raise
        trusted = None
    if trusted is None:
        return {
            "trusted": None,
            "authenticated": False,
            "plan": "guest",
            "is_admin": False,
            "video_slots": 0,
            "storage": {"used": 0, "limit": 0, "free": 0, "full": False, "storedBytes": 0},
        }
    user_id = trusted["legacy_user_id"]
    with connect() as conn:
        user = conn.execute("SELECT plan, role FROM users WHERE id = ?", (user_id,)).fetchone()
        quota = quota_for_user(conn, user, user_id)
        storage_state = storage_state_for_user(
            conn,
            user_id,
            limit=int(quota["video_slots"] or 0),
        )
    return {
        "trusted": trusted,
        "authenticated": True,
        "plan": str(row_get(user, "plan") or "free").lower(),
        "is_admin": str(row_get(user, "role") or "") == "admin",
        "video_slots": int(quota["video_slots"] or 0),
        "storage": {
            "used": storage_state.active,
            "limit": storage_state.limit,
            "free": storage_state.free,
            "full": storage_state.full,
            "storedBytes": storage_state.stored_bytes,
        },
    }


def video_submit_failure(error: Exception, settings: Any) -> dict[str, Any]:
    """Build persisted private diagnostics and a product-safe public failure."""

    provider_rejection = isinstance(error, OpenRouterVideoRequestError)
    route_detail = getattr(error, "detail", None)
    public_error = (
        openrouter_video_public_error(error)
        if provider_rejection
        else str(route_detail)
        if isinstance(route_detail, str) and route_detail.strip()
        else "Не удалось связаться с видеосервисом. Попробуйте снова через несколько минут."
    )
    updated_settings = dict(settings) if isinstance(settings, dict) else {}
    updated_settings["openrouterSubmitError"] = str(error)[:1000]
    return {
        "public": public_error,
        "status": 422 if provider_rejection else int(getattr(error, "status_code", 502) or 502),
        "settings": updated_settings,
    }


def public_video_error_message(value: Any) -> str | None:
    """Do not expose provider URLs or transport diagnostics in the video UI."""

    message = str(value or "").strip()
    if not message:
        return None
    lowered = message.lower()
    if "openrouter" in lowered or "/api/v1/videos" in lowered or "bad request" in lowered:
        return "Модель отклонила исходное изображение или параметры. Выберите другой кадр либо измените настройки."
    if any(marker in lowered for marker in ("traceback", "http://", "https://", "api key", "connection refused")):
        return "Видеосервис не ответил. Попробуйте снова через несколько минут."
    return message


def publication_fields(
    publication: Any,
    *,
    row_get: Callable[[Any, str], Any],
    publication_ready: Callable[[Any], bool],
) -> dict[str, Any]:
    status = str(row_get(publication, "status") or "") if publication is not None else ""
    ready = bool(publication is not None and publication_ready(publication))
    return {
        "published": ready,
        "publicationId": row_get(publication, "id") if publication is not None else None,
        "publicationStatus": "published" if ready else (status or None),
        "publicationError": row_get(publication, "media_error") if publication is not None else None,
    }


def job_payload(
    row: Any,
    settings: dict[str, Any],
    *,
    publication: Any = None,
    row_get: Callable[[Any, str], Any],
    publication_ready: Callable[[Any], bool],
) -> dict[str, Any]:
    return {
        "id": row["id"],
        "mode": row["mode"],
        "status": row["status"],
        "progress": int(row["progress"] or 0),
        "prompt": row["prompt_original"] or "",
        "error": public_video_error_message(row["error_message"]),
        "createdAt": row["created_at"],
        "completedAt": row["completed_at"],
        "model": settings.get("model") or settings.get("openrouterModel"),
        "duration": settings.get("duration"),
        "resolution": settings.get("resolution"),
        "aspectRatio": settings.get("aspectRatio"),
        "tokenCost": settings.get("tokenCost"),
        "videoUrl": f"/api/video/media/{row['id']}" if settings.get("localFile") else None,
        "galleryVideoId": settings.get("galleryVideoId"),
        "galleryDeleted": bool(settings.get("galleryDeleted")),
        "generateAudio": bool(settings.get("generateAudio")),
        "sourceHistory": settings.get("sourceHistory") if isinstance(settings.get("sourceHistory"), list) else [],
        **publication_fields(
            publication,
            row_get=row_get,
            publication_ready=publication_ready,
        ),
    }


def gallery_item(
    row: Any,
    settings: dict[str, Any],
    *,
    publication: Any = None,
    include_feed_media: bool = False,
    row_get: Callable[[Any, str], Any],
    publication_ready: Callable[[Any], bool],
) -> dict[str, Any]:
    fields = publication_fields(
        publication,
        row_get=row_get,
        publication_ready=publication_ready,
    )
    publication_id = fields["publicationId"]
    use_feed_media = bool(include_feed_media and fields["published"] and publication_id)
    private_url = row["url"]
    video_url = f"/api/feed/video/{publication_id}?variant=full" if use_feed_media else private_url
    poster_url = f"/api/feed/media/{publication_id}?variant=large" if fields["published"] and publication_id else None
    return {
        "id": row["id"],
        "mediaType": "video",
        "videoUrl": video_url,
        "viewerSrc": video_url,
        "downloadUrl": video_url,
        "thumbnailUrl": poster_url,
        "width": int(row["width"] or 0),
        "height": int(row["height"] or 0),
        "duration": int(row["duration_seconds"] or 0),
        "aspectRatio": row["aspect_ratio"],
        "mode": row["mode"],
        "modeLabel": "Видео",
        "provider": row["provider"],
        "model": settings.get("model") or settings.get("openrouterModel"),
        "prompt": row["prompt_original"] or "",
        "promptOriginal": row["prompt_original"] or "",
        "settings": settings,
        "sources": settings.get("sourceHistory") if isinstance(settings.get("sourceHistory"), list) else [],
        "favorite": bool(row["is_favorite"]),
        **fields,
        "feedPublicationId": publication_id,
        "publishedAt": row_get(publication, "created_at") if fields["published"] else None,
        "feedMediaStatus": "ready" if fields["published"] else fields["publicationStatus"],
        "views": int(row_get(publication, "view_count") or 0) if publication is not None else 0,
        "createdAt": row["created_at"],
        "storedBytes": int(row["stored_bytes"] or 0),
    }
