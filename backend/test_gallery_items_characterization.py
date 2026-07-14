from __future__ import annotations

import main


def test_feed_publication_ready_preserves_short_circuit_row_access(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(main, "_row_get", lambda row, key: calls.append(key) or row.get(key))

    assert main._feed_publication_ready(None) is False
    assert calls == []

    assert main._feed_publication_ready({"status": "draft"}) is False
    assert calls == ["status"]
    calls.clear()

    assert main._feed_publication_ready({"status": "published", "media_ready_at": None}) is False
    assert calls == ["status", "media_ready_at"]
    calls.clear()

    publication = {
        "status": "published",
        "media_ready_at": "ready",
        "feed_thumb_name": "thumb.webp",
        "feed_large_name": "large.webp",
    }
    assert main._feed_publication_ready(publication) is True
    assert calls == ["status", "media_ready_at", "feed_thumb_name", "feed_large_name"]


def test_gallery_page_item_preserves_exact_payload_and_callback_order(monkeypatch) -> None:
    events: list[tuple[object, ...]] = []
    settings = {
        "modelProfile": "provider/model",
        "preset": "preset-a",
        "loras": ["lora-a"],
        "seed": 42,
        "generationTimeMs": 1250,
        "tokenCost": 7,
        "openrouterBilling": {"chargedTokens": 7},
    }
    row = {
        "id": "img-1",
        "thumbnail_url": "/api/media/thumb.webp",
        "url": "/api/media/image.webp",
        "prompt_original": "original",
        "prompt_translated": "translated",
        "mode": "edit",
        "provider": "openrouter",
        "settings_json": "serialized-settings",
        "width": "640",
        "height": 480,
        "created_at": "created",
        "is_favorite": 1,
    }
    publication = {"id": "pub-1", "created_at": "published", "view_count": 9}
    monkeypatch.setattr(main.json, "loads", lambda raw: events.append(("json", raw)) or settings)
    monkeypatch.setattr(main, "_row_get", lambda value, key: events.append(("row_get", key)) or value.get(key))
    monkeypatch.setattr(main, "_feed_publication_ready", lambda value: events.append(("ready", value)) or True)
    monkeypatch.setattr(main, "_media_file_size_from_url", lambda url: events.append(("file", url)) or 321)
    monkeypatch.setattr(main, "_gallery_mode_label", lambda mode: events.append(("mode", mode)) or "Сборка")
    monkeypatch.setattr(main, "_user_model_name", lambda raw: events.append(("display", raw)) or "Display")
    monkeypatch.setattr(
        main,
        "_gallery_model_info",
        lambda value, provider: events.append(("model", value, provider)) or {"fullName": "Full"},
    )
    monkeypatch.setattr(
        main,
        "_gallery_aspect_ratio",
        lambda width, height: events.append(("aspect", width, height)) or "4:3",
    )
    monkeypatch.setattr(
        main,
        "_gallery_public_params",
        lambda **kwargs: events.append(("params", kwargs)) or [{"label": "A", "value": "B"}],
    )
    monkeypatch.setattr(main, "_gallery_source_ids", lambda value: events.append(("sources", value)) or ["source-1"])

    result = main._gallery_page_item(row, publication, include_feed_media=True)

    assert result == {
        "id": "img-1",
        "imageId": "img-1",
        "src": "/api/feed/media/pub-1?variant=thumb",
        "thumbnailUrl": "/api/feed/media/pub-1?variant=thumb",
        "viewerSrc": "/api/feed/media/pub-1?variant=large",
        "downloadUrl": "/api/feed/media/pub-1?variant=large",
        "prompt": "original",
        "promptOriginal": "original",
        "promptTranslated": "translated",
        "mode": "edit",
        "modeLabel": "Сборка",
        "provider": "openrouter",
        "model": "Display",
        "modelProfile": "Display",
        "modelInfo": {"fullName": "Full"},
        "preset": "preset-a",
        "loras": ["lora-a"],
        "seed": 42,
        "width": 640,
        "height": 480,
        "aspect": "4:3",
        "aspectRatio": "4:3",
        "createdAt": "created",
        "date": "created",
        "generationTimeMs": 1250,
        "genTime": 1250,
        "tokenCost": 7,
        "openrouterBilling": {"chargedTokens": 7},
        "fileSizeBytes": 321,
        "publicParams": [{"label": "A", "value": "B"}],
        "favorite": True,
        "isFavorite": True,
        "published": True,
        "feedPublicationId": "pub-1",
        "publishedAt": "published",
        "feedMediaStatus": "ready",
        "views": 9,
        "likes": 0,
        "saves": 0,
        "remixes": 0,
        "sourceIds": ["source-1"],
    }
    assert events == [
        ("json", "serialized-settings"),
        ("row_get", "id"),
        ("ready", publication),
        ("file", "/api/media/image.webp"),
        ("mode", "edit"),
        ("display", "provider/model"),
        ("display", "provider/model"),
        ("model", settings, "openrouter"),
        ("aspect", 640, 480),
        ("aspect", 640, 480),
        (
            "params",
            {
                "image_id": "img-1",
                "mode": "edit",
                "provider": "openrouter",
                "width": 640,
                "height": 480,
                "url": "/api/media/image.webp",
                "created_at": "created",
                "settings": settings,
            },
        ),
        ("row_get", "created_at"),
        ("row_get", "view_count"),
        ("sources", settings),
    ]


def test_gallery_page_item_preserves_missing_publication_and_settings_defaults() -> None:
    row = {
        "id": "img-empty",
        "thumbnail_url": None,
        "url": None,
        "prompt_original": None,
        "prompt_translated": "translated-only",
        "mode": None,
        "provider": None,
        "settings_json": None,
        "width": None,
        "height": None,
        "created_at": None,
        "is_favorite": 0,
    }

    result = main._gallery_page_item(row)

    assert result["prompt"] == "translated-only"
    assert result["width"] == result["height"] == 0
    assert result["loras"] == []
    assert result["generationTimeMs"] == result["genTime"] == 0
    assert result["published"] is False
    assert result["feedPublicationId"] is None
    assert result["publishedAt"] is None
    assert result["feedMediaStatus"] is None
    assert result["views"] == 0
