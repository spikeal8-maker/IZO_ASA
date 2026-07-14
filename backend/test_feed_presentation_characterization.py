from __future__ import annotations

import main


def test_feed_generation_snapshot_preserves_exact_payload_and_callback_order(monkeypatch) -> None:
    events: list[tuple[object, ...]] = []
    settings = {
        "styleName": "cinematic",
        "modelProfile": "provider/model",
        "generationTimeMs": 1234,
        "seed": 42,
    }
    image = {
        "id": "img-1",
        "settings_json": "serialized-settings",
        "width": "640",
        "height": 480,
        "provider": "openrouter",
        "prompt_original": "  original prompt  ",
        "mode": "edit",
        "url": "/api/media/image.webp",
        "created_at": "created",
    }
    connection = object()

    monkeypatch.setattr(
        main,
        "_row_get",
        lambda row, key: events.append(("row_get", key)) or row.get(key),
    )
    monkeypatch.setattr(
        main,
        "safe_json_load",
        lambda raw: events.append(("json", raw)) or settings,
    )
    monkeypatch.setattr(
        main,
        "_gallery_model_info",
        lambda value, provider: events.append(("model_info", value, provider)) or {"fullName": "Full"},
    )
    monkeypatch.setattr(
        main,
        "_user_model_name",
        lambda value: events.append(("model_name", value)) or "Display",
    )
    monkeypatch.setattr(
        main,
        "_feed_aspect_ratio",
        lambda width, height: events.append(("aspect", width, height)) or "4:3",
    )
    monkeypatch.setattr(
        main,
        "_gallery_public_params",
        lambda **kwargs: events.append(("params", kwargs)) or [{"label": "A", "value": "B"}],
    )
    monkeypatch.setattr(
        main,
        "_feed_source_history_payload",
        lambda conn, image_id: events.append(("history", conn, image_id)) or [{"kind": "source"}],
    )
    monkeypatch.setattr(
        main,
        "_public_token_cost",
        lambda value: events.append(("token", value)) or 7,
    )
    monkeypatch.setattr(
        main,
        "_media_file_size_from_url",
        lambda url: events.append(("file", url)) or 321,
    )

    result = main._feed_generation_snapshot(connection, image)

    assert result == {
        "prompt": "original prompt",
        "mode": "edit",
        "provider": "openrouter",
        "style": "cinematic",
        "model": "Display",
        "modelInfo": {"fullName": "Full"},
        "width": 640,
        "height": 480,
        "aspectRatio": "4:3",
        "generationParams": [{"label": "A", "value": "B"}],
        "sourceHistory": [{"kind": "source"}],
        "tokenCost": 7,
        "generationTimeMs": 1234,
        "fileSizeBytes": 321,
        "seed": 42,
        "generatedAt": "created",
    }
    assert events == [
        ("row_get", "settings_json"),
        ("json", "serialized-settings"),
        ("row_get", "width"),
        ("row_get", "height"),
        ("row_get", "provider"),
        ("model_info", settings, "openrouter"),
        ("row_get", "prompt_original"),
        ("row_get", "mode"),
        ("row_get", "provider"),
        ("model_name", "provider/model"),
        ("aspect", 640, 480),
        ("row_get", "mode"),
        ("row_get", "provider"),
        ("row_get", "url"),
        ("row_get", "created_at"),
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
        ("history", connection, "img-1"),
        ("token", settings),
        ("row_get", "url"),
        ("file", "/api/media/image.webp"),
        ("row_get", "created_at"),
    ]


def test_feed_generation_snapshot_preserves_invalid_settings_defaults(monkeypatch) -> None:
    seen: list[object] = []
    image = {
        "id": "img-empty",
        "settings_json": "[]",
        "width": None,
        "height": None,
        "provider": None,
        "prompt_original": None,
        "mode": None,
        "url": None,
        "created_at": None,
    }
    monkeypatch.setattr(main, "safe_json_load", lambda raw: [])
    monkeypatch.setattr(
        main,
        "_gallery_model_info",
        lambda settings, provider: seen.append(settings) or {},
    )
    monkeypatch.setattr(main, "_gallery_public_params", lambda **kwargs: [])
    monkeypatch.setattr(main, "_feed_source_history_payload", lambda conn, image_id: [])
    monkeypatch.setattr(main, "_public_token_cost", lambda settings: None)
    monkeypatch.setattr(main, "_media_file_size_from_url", lambda url: None)

    result = main._feed_generation_snapshot(object(), image)

    assert seen == [{}]
    assert result["prompt"] == ""
    assert result["style"] is None
    assert result["width"] == result["height"] == 0
    assert result["generationTimeMs"] is None
    assert result["seed"] is None
    assert result["generatedAt"] is None
