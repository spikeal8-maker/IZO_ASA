from __future__ import annotations

import main


IMAGE_CONFIG = {
    "enabled": {
        "text_to_image": ["openai/image-a", "vendor/image-b"],
        "image_to_image": ["openai/image-a"],
    },
    "access": {
        "text_to_image": {
            "mini": ["openai/image-a"],
            "plus": ["openai/image-a", "vendor/image-b"],
        },
        "image_to_image": {
            "mini": ["openai/image-a"],
            "plus": ["openai/image-a"],
        },
    },
}

VIDEO_CONFIG = {
    "enabled": {
        "text_to_video": ["vendor/video-a"],
        "image_to_video": ["vendor/video-a", "vendor/video-b"],
    },
    "access": {
        "text_to_video": {
            "mini": ["vendor/video-a"],
            "plus": ["vendor/video-a", "vendor/video-disabled"],
        },
        "image_to_video": {
            "mini": ["vendor/video-a"],
            "plus": ["vendor/video-a", "vendor/video-b"],
        },
    },
}


def test_tariff_model_counts_are_distinct_and_access_based() -> None:
    counts = main.tariff_model_counts(IMAGE_CONFIG, VIDEO_CONFIG)

    assert counts["free"] == {"image_model_count": 1, "video_model_count": 0}
    assert counts["mini"] == {"image_model_count": 2, "video_model_count": 1}
    assert counts["plus"] == {"image_model_count": 3, "video_model_count": 2}
    assert counts["pro"] == {"image_model_count": 1, "video_model_count": 0}


def test_tariff_payload_adds_counts_without_persisting_manual_totals(monkeypatch) -> None:
    tariffs = main.normalize_tariffs()
    monkeypatch.setattr(main, "get_tariff_config", lambda conn=None: tariffs)
    monkeypatch.setattr(
        main,
        "_saved_setting",
        lambda key: IMAGE_CONFIG if key == "openrouter_models" else VIDEO_CONFIG,
    )

    payload = main.tariff_config_with_model_counts()

    assert payload["plus"]["gallery_slots"] == tariffs["plus"]["gallery_slots"]
    assert payload["plus"]["image_model_count"] == 3
    assert payload["plus"]["video_model_count"] == 2
    assert "image_model_count" not in tariffs["plus"]
    assert "video_model_count" not in tariffs["plus"]
