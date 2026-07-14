from __future__ import annotations

import inspect

import app.services.feed_presentation as feed_presentation_module
from app.services.feed_presentation import feed_generation_snapshot


def test_feed_presentation_module_is_import_safe() -> None:
    source = inspect.getsource(feed_presentation_module).lower()

    for forbidden in ("import main", "fastapi", "pydantic", "sqlite3", "pathlib", "httpx", "os.environ"):
        assert forbidden not in source


def test_feed_generation_snapshot_preserves_injected_contract() -> None:
    events: list[tuple[object, ...]] = []
    settings = {"styleName": "style", "modelProfile": "model", "seed": 9}
    image = {
        "id": "img",
        "settings_json": "raw",
        "width": "10",
        "height": 20,
        "provider": "provider",
        "prompt_original": " prompt ",
        "mode": "mode",
        "url": "url",
        "created_at": "created",
    }
    connection = object()

    result = feed_generation_snapshot(
        connection,
        image,
        load_settings=lambda raw: events.append(("json", raw)) or settings,
        row_get=lambda row, key: events.append(("row_get", key)) or row.get(key),
        model_info=lambda value, provider: events.append(("model_info", value, provider)) or {},
        model_display_name=lambda value: events.append(("model_name", value)) or "Display",
        aspect_ratio=lambda width, height: events.append(("aspect", width, height)) or "1:2",
        public_params=lambda **kwargs: events.append(("params", kwargs)) or [],
        source_history=lambda conn, image_id: events.append(("history", conn, image_id)) or [],
        token_cost=lambda value: events.append(("token", value)) or 3,
        media_file_size=lambda url: events.append(("file", url)) or 100,
    )

    assert result == {
        "prompt": "prompt",
        "mode": "mode",
        "provider": "provider",
        "style": "style",
        "model": "Display",
        "modelInfo": {},
        "width": 10,
        "height": 20,
        "aspectRatio": "1:2",
        "generationParams": [],
        "sourceHistory": [],
        "tokenCost": 3,
        "generationTimeMs": None,
        "fileSizeBytes": 100,
        "seed": 9,
        "generatedAt": "created",
    }
    assert [event[0] for event in events] == [
        "row_get",
        "json",
        "row_get",
        "row_get",
        "row_get",
        "model_info",
        "row_get",
        "row_get",
        "row_get",
        "model_name",
        "aspect",
        "row_get",
        "row_get",
        "row_get",
        "row_get",
        "params",
        "history",
        "token",
        "row_get",
        "file",
        "row_get",
    ]


def test_feed_generation_snapshot_replaces_non_mapping_settings() -> None:
    seen: list[object] = []
    image = {
        "id": "img",
        "settings_json": "[]",
        "width": None,
        "height": None,
        "provider": None,
        "prompt_original": None,
        "mode": None,
        "url": None,
        "created_at": None,
    }

    result = feed_generation_snapshot(
        object(),
        image,
        load_settings=lambda raw: [],
        row_get=lambda row, key: row.get(key),
        model_info=lambda value, provider: seen.append(value) or {},
        model_display_name=lambda value: "Unknown",
        aspect_ratio=lambda width, height: None,
        public_params=lambda **kwargs: [],
        source_history=lambda conn, image_id: [],
        token_cost=lambda value: None,
        media_file_size=lambda url: None,
    )

    assert seen == [{}]
    assert result["prompt"] == ""
    assert result["width"] == result["height"] == 0
    assert result["style"] is None
