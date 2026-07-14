"""Import-safe gallery page item mapping."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


def feed_publication_ready(
    publication: Any | None,
    *,
    row_get: Callable[[Any, str], Any],
) -> bool:
    return bool(
        publication is not None
        and row_get(publication, "status") == "published"
        and row_get(publication, "media_ready_at")
        and row_get(publication, "feed_thumb_name")
        and row_get(publication, "feed_large_name")
    )


def gallery_page_item(
    row: Any,
    publication: Any | None = None,
    *,
    include_feed_media: bool = False,
    load_settings: Callable[[str], Any],
    row_get: Callable[[Any, str], Any],
    publication_ready: Callable[[Any | None], bool],
    media_file_size: Callable[[str | None], int | None],
    mode_label: Callable[[str | None], str],
    model_display_name: Callable[[Any], str],
    model_info: Callable[[Mapping[str, Any], str | None], Mapping[str, str]],
    aspect_ratio: Callable[[int | None, int | None], str | None],
    public_params: Callable[..., list[dict[str, str]]],
    source_ids: Callable[[Mapping[str, Any]], list[str]],
) -> dict[str, Any]:
    settings = load_settings(row["settings_json"] or "{}")
    publication_id = row_get(publication, "id") if publication is not None else None
    feed_ready = publication_ready(publication)
    published = bool(publication_id and feed_ready)
    thumb_url = row["thumbnail_url"]
    image_url = row["url"]
    if include_feed_media and publication_id and feed_ready:
        thumb_url = f"/api/feed/media/{publication_id}?variant=thumb"
        image_url = f"/api/feed/media/{publication_id}?variant=large"
    prompt = row["prompt_original"] or row["prompt_translated"] or ""
    width = int(row["width"] or 0)
    height = int(row["height"] or 0)
    file_size = media_file_size(row["url"])
    return {
        "id": row["id"],
        "imageId": row["id"],
        "src": thumb_url,
        "thumbnailUrl": thumb_url,
        "viewerSrc": image_url,
        "downloadUrl": image_url,
        "prompt": prompt,
        "promptOriginal": row["prompt_original"] or "",
        "promptTranslated": row["prompt_translated"] or "",
        "mode": row["mode"],
        "modeLabel": mode_label(row["mode"]),
        "provider": row["provider"],
        "model": model_display_name(settings.get("modelProfile") or row["provider"]),
        "modelProfile": model_display_name(settings.get("modelProfile") or row["provider"]),
        "modelInfo": model_info(settings, row["provider"]),
        "preset": settings.get("preset") or settings.get("styleName"),
        "loras": settings.get("loras") if isinstance(settings.get("loras"), list) else [],
        "seed": settings.get("seed"),
        "width": width,
        "height": height,
        "aspect": aspect_ratio(width, height),
        "aspectRatio": aspect_ratio(width, height),
        "createdAt": row["created_at"],
        "date": row["created_at"],
        "generationTimeMs": settings.get("generationTimeMs", 0),
        "genTime": settings.get("generationTimeMs", 0),
        "tokenCost": settings.get("tokenCost"),
        "openrouterBilling": settings.get("openrouterBilling")
        if isinstance(settings.get("openrouterBilling"), dict)
        else None,
        "fileSizeBytes": file_size,
        "publicParams": public_params(
            image_id=row["id"],
            mode=row["mode"],
            provider=row["provider"],
            width=width,
            height=height,
            url=row["url"],
            created_at=row["created_at"],
            settings=settings,
        ),
        "favorite": bool(row["is_favorite"]),
        "isFavorite": bool(row["is_favorite"]),
        "published": published,
        "feedPublicationId": publication_id,
        "publishedAt": row_get(publication, "created_at") if publication is not None else None,
        "feedMediaStatus": "ready" if feed_ready else ("missing" if publication is not None else None),
        "views": row_get(publication, "view_count") if publication is not None else 0,
        "likes": 0,
        "saves": 0,
        "remixes": 0,
        "sourceIds": source_ids(settings),
    }
