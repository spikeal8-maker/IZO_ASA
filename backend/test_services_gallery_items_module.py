from __future__ import annotations

import inspect

import app.services.gallery_items as gallery_items_module
from app.services.gallery_items import feed_publication_ready, gallery_page_item


def test_gallery_items_module_is_import_safe() -> None:
    source = inspect.getsource(gallery_items_module).lower()

    for forbidden in ("import main", "fastapi", "pydantic", "sqlite3", "pathlib", "httpx", "os.environ"):
        assert forbidden not in source


def test_feed_publication_ready_preserves_short_circuit() -> None:
    calls: list[str] = []
    row_get = lambda row, key: calls.append(key) or row.get(key)

    assert feed_publication_ready(None, row_get=row_get) is False
    assert calls == []
    assert feed_publication_ready({"status": "draft"}, row_get=row_get) is False
    assert calls == ["status"]
    calls.clear()
    assert feed_publication_ready(
        {
            "status": "published",
            "media_ready_at": "ready",
            "feed_thumb_name": "thumb",
            "feed_large_name": "large",
        },
        row_get=row_get,
    ) is True
    assert calls == ["status", "media_ready_at", "feed_thumb_name", "feed_large_name"]


def test_gallery_page_item_preserves_injected_order_and_feed_urls() -> None:
    events: list[tuple[object, ...]] = []
    settings = {"modelProfile": "model", "loras": "invalid", "styleName": "style"}
    row = {
        "id": "img",
        "thumbnail_url": "thumb",
        "url": "image",
        "prompt_original": None,
        "prompt_translated": "translated",
        "mode": "edit",
        "provider": "provider",
        "settings_json": "raw",
        "width": "10",
        "height": 20,
        "created_at": "created",
        "is_favorite": 1,
    }
    publication = {"id": "pub", "created_at": "published", "view_count": 4}

    result = gallery_page_item(
        row,
        publication,
        include_feed_media=True,
        load_settings=lambda raw: events.append(("json", raw)) or settings,
        row_get=lambda value, key: events.append(("row_get", key)) or value.get(key),
        publication_ready=lambda value: events.append(("ready", value)) or True,
        media_file_size=lambda url: events.append(("file", url)) or 100,
        mode_label=lambda mode: events.append(("mode", mode)) or "Mode",
        model_display_name=lambda raw: events.append(("display", raw)) or "Display",
        model_info=lambda value, provider: events.append(("model", value, provider)) or {},
        aspect_ratio=lambda width, height: events.append(("aspect", width, height)) or "1:2",
        public_params=lambda **kwargs: events.append(("params", kwargs)) or [],
        source_ids=lambda value: events.append(("sources", value)) or [],
    )

    assert result["src"] == "/api/feed/media/pub?variant=thumb"
    assert result["viewerSrc"] == "/api/feed/media/pub?variant=large"
    assert result["prompt"] == "translated"
    assert result["preset"] == "style"
    assert result["loras"] == []
    assert result["width"] == 10
    assert result["height"] == 20
    assert result["published"] is True
    assert result["views"] == 4
    assert [event[0] for event in events] == [
        "json",
        "row_get",
        "ready",
        "file",
        "mode",
        "display",
        "display",
        "model",
        "aspect",
        "aspect",
        "params",
        "row_get",
        "row_get",
        "sources",
    ]
