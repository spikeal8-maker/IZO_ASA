from __future__ import annotations

from types import SimpleNamespace

import pytest

import main


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (1024, 1024, "1:1"),
        (1920, 1080, "16:9"),
        (768, 1024, "3:4"),
        (None, 1024, None),
        (1024, None, None),
        (0, 1024, None),
        (-10, 20, "-1:2"),
    ],
)
def test_aspect_ratio_preserves_legacy_reduction(width, height, expected) -> None:
    assert main._gallery_aspect_ratio(width, height) == expected


def test_mode_labels_preserve_all_legacy_aliases() -> None:
    expected = {
        "text_to_image": "По тексту",
        "image_to_image": "По фото",
        "edit": "Сборка",
        "paint": "Редактор",
        "inpaint": "Инпейнт",
        "outpaint": "Аутпейнт",
        "try_on": "Примерка",
        "texture_transfer": "Перенос текстуры",
        "remove_background": "Удаление фона",
        "faceswap": "Лицо",
        "face": "Лицо",
        "face_swap": "Лицо",
        "drawing": "Редактор",
        "editor": "Сборка",
    }

    assert {mode: main._gallery_mode_label(mode) for mode in expected} == expected


def test_mode_label_strips_only_for_lookup_and_preserves_unknown_fallback() -> None:
    assert main._gallery_mode_label(" text_to_image ") == "По тексту"
    assert main._gallery_mode_label(" custom ") == " custom "
    assert main._gallery_mode_label(None) == "По тексту"


def test_mode_label_ignores_unrelated_corrupt_admin_cache_timestamp(monkeypatch) -> None:
    monkeypatch.setitem(main._admin_models_page_cache, "ts", "corrupt-unused-timestamp")

    assert main._gallery_mode_label("text_to_image") == "По тексту"


def test_source_ids_preserve_precedence_slice_before_filter_and_string_coercion() -> None:
    assert main._gallery_source_ids(
        {
            "sourceImageIds": [None, "first", "", " second ", "ignored-after-four"],
            "source_image_ids": ["fallback"],
            "sourceIds": ["last"],
        }
    ) == ["first", " second "]
    assert main._gallery_source_ids({"source_image_ids": [1, 2]}) == ["1", "2"]
    assert main._gallery_source_ids({"sourceIds": ["last"]}) == ["last"]


@pytest.mark.parametrize("value", ["not-a-list", {"id": "x"}, 42, None])
def test_source_ids_reject_non_list_values(value) -> None:
    assert main._gallery_source_ids({"sourceImageIds": value}) == []


@pytest.mark.parametrize("raw", [None, "comfyui", "local_flux_v2", "flux-klein-custom"])
def test_model_info_maps_local_models_to_exact_izo_base_payload(raw) -> None:
    settings = {"modelProfile": raw} if raw is not None else {}

    assert main._gallery_model_info(settings, "comfyui") == {
        "shortName": "ИЗО Base",
        "fullName": "ИЗО Base · ИЗО · выпуск: 2026",
        "providerName": "ИЗО",
        "release": "2026",
    }


def test_model_info_billing_overrides_catalog_display_and_uses_release_map(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "OPENROUTER_PRICE_CATALOG",
        {"vendor/model": SimpleNamespace(name="Catalog Name", provider="Catalog Maker")},
    )
    monkeypatch.setitem(main.MODEL_RELEASE_YEAR_BY_ID, "vendor/model", "2025")

    result = main._gallery_model_info(
        {
            "modelProfile": "vendor/model",
            "openrouterBilling": {"modelName": "Billing Name", "modelProvider": "Billing Maker"},
        }
    )

    assert result == {
        "shortName": "Billing Name",
        "fullName": "Billing Name · Billing Maker · выпуск: 2025",
        "providerName": "Billing Maker",
        "release": "2025",
    }


def test_model_info_uses_catalog_then_display_callback_and_preserves_raw_precedence(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "OPENROUTER_PRICE_CATALOG",
        {"profile/model": SimpleNamespace(name="Catalog Name", provider="Catalog Maker")},
    )
    monkeypatch.setattr(main, "_user_model_name", lambda raw: f"display:{raw}")

    catalog = main._gallery_model_info(
        {"modelProfile": "profile/model", "openrouterModel": "ignored/model"},
        "ignored-provider",
    )
    fallback = main._gallery_model_info(
        {"openrouterModel": "fallback/model", "openrouterBilling": "not-a-dict"},
        "ignored-provider",
    )

    assert catalog["shortName"] == "Catalog Name"
    assert catalog["providerName"] == "Catalog Maker"
    assert fallback == {
        "shortName": "display:fallback/model",
        "fullName": "display:fallback/model · выпуск: 2026",
        "providerName": "",
        "release": "2026",
    }


def test_public_params_preserve_callback_order_labels_and_zero_token_cost(monkeypatch) -> None:
    events: list[tuple[object, ...]] = []

    monkeypatch.setattr(
        main,
        "_gallery_model_info",
        lambda settings, provider: events.append(("model", settings, provider)) or {"fullName": "Model Full"},
    )
    monkeypatch.setattr(
        main,
        "_public_token_cost",
        lambda settings: events.append(("tokens", settings)) or 0,
    )
    monkeypatch.setattr(
        main,
        "_gallery_aspect_ratio",
        lambda width, height: events.append(("aspect", width, height)) or "3:2",
    )
    monkeypatch.setattr(
        main,
        "_media_file_size_from_url",
        lambda url: events.append(("file_size", url)) or 2048,
    )
    monkeypatch.setattr(
        main,
        "_format_public_bytes",
        lambda value: events.append(("bytes", value)) or "2,0 КБ",
    )
    monkeypatch.setattr(
        main,
        "_format_public_duration",
        lambda value: events.append(("duration", value)) or "1,5 с",
    )
    monkeypatch.setattr(
        main,
        "_format_public_datetime",
        lambda value: events.append(("datetime", value)) or "14.07.2026, 08:00:00",
    )
    monkeypatch.setattr(
        main,
        "_gallery_mode_label",
        lambda value: events.append(("mode", value)) or "По тексту",
    )
    settings = {"generationTimeMs": 1500}

    result = main._gallery_public_params(
        image_id="unused-image-id",
        mode="text_to_image",
        provider="openrouter",
        width=1200,
        height=800,
        url="/api/media/image.webp",
        created_at="2026-07-14T05:00:00Z",
        settings=settings,
    )

    assert result == [
        {"label": "Токены", "value": "0 ток."},
        {"label": "Разрешение", "value": "1200×800"},
        {"label": "Формат", "value": "3:2"},
        {"label": "Вес файла", "value": "2,0 КБ"},
        {"label": "Время генерации", "value": "1,5 с"},
        {"label": "Дата генерации", "value": "14.07.2026, 08:00:00"},
        {"label": "Режим", "value": "По тексту"},
        {"label": "Полное наименование модели", "value": "Model Full"},
    ]
    assert events == [
        ("model", settings, "openrouter"),
        ("tokens", settings),
        ("tokens", settings),
        ("aspect", 1200, 800),
        ("file_size", "/api/media/image.webp"),
        ("bytes", 2048),
        ("duration", 1500),
        ("datetime", "2026-07-14T05:00:00Z"),
        ("mode", "text_to_image"),
    ]


def test_public_params_filter_empty_values_after_calling_every_formatter(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(main, "_gallery_model_info", lambda settings, provider: {"fullName": ""})
    monkeypatch.setattr(main, "_public_token_cost", lambda settings: None)
    monkeypatch.setattr(main, "_gallery_aspect_ratio", lambda width, height: calls.append("aspect") or None)
    monkeypatch.setattr(main, "_media_file_size_from_url", lambda url: calls.append("file_size") or None)
    monkeypatch.setattr(main, "_format_public_bytes", lambda value: calls.append("bytes") or None)
    monkeypatch.setattr(main, "_format_public_duration", lambda value: calls.append("duration") or None)
    monkeypatch.setattr(main, "_format_public_datetime", lambda value: calls.append("datetime") or None)
    monkeypatch.setattr(main, "_gallery_mode_label", lambda value: calls.append("mode") or "")

    result = main._gallery_public_params(
        image_id="first-unused-id",
        mode=None,
        provider=None,
        width=0,
        height=0,
        url=None,
        created_at=None,
        settings={},
    )
    second = main._gallery_public_params(
        image_id="different-unused-id",
        mode=None,
        provider=None,
        width=0,
        height=0,
        url=None,
        created_at=None,
        settings={},
    )

    assert result == second == []
    assert calls == ["aspect", "file_size", "bytes", "duration", "datetime", "mode"] * 2


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (0, None),
        (-1, None),
        (1, "1 Б"),
        (1023, "1023 Б"),
        (1024, "1,0 КБ"),
        (1536, "1,5 КБ"),
        (1024**2, "1,0 МБ"),
        (1024**3, "1,0 ГБ"),
    ],
)
def test_public_bytes_preserve_units_thresholds_and_decimal_comma(value, expected) -> None:
    assert main._format_public_bytes(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (0, None),
        (-1, None),
        ("invalid", None),
        (999, "999 мс"),
        (1000, "1,0 с"),
        (1249, "1,2 с"),
        (1250, "1,2 с"),
    ],
)
def test_public_duration_preserves_coercion_threshold_and_rounding(value, expected) -> None:
    assert main._format_public_duration(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("2026-07-14T05:00:00Z", "14.07.2026, 08:00:00"),
        ("2026-07-14T05:00:00", "14.07.2026, 08:00:00"),
        ("2026-07-14T05:00:00+03:00", "14.07.2026, 05:00:00"),
        ("not-a-date", "not-a-date"),
    ],
)
def test_public_datetime_preserves_moscow_conversion_and_invalid_fallback(value, expected) -> None:
    assert main._format_public_datetime(value) == expected


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ({"tokenCost": "7", "openrouterBilling": {"chargedTokens": 8, "actualTokens": 9}}, 7),
        ({"tokenCost": "invalid", "openrouterBilling": {"chargedTokens": "8", "actualTokens": 9}}, 8),
        ({"openrouterBilling": {"chargedTokens": "invalid", "actualTokens": "9"}}, 9),
        ({"tokenCost": 0}, 0),
        ({"openrouterBilling": "not-a-dict"}, None),
        ({}, None),
    ],
)
def test_public_token_cost_preserves_precedence_coercion_and_fallback(settings, expected) -> None:
    assert main._public_token_cost(settings) == expected


def test_row_to_image_preserves_exact_payload_and_callback_order(monkeypatch) -> None:
    events: list[tuple[object, ...]] = []
    settings = {
        "seed": 42,
        "modelProfile": "provider/model",
        "loras": ["lora-a"],
        "preset": "preset-a",
        "generationTimeMs": 1250,
        "tokenCost": 7,
        "openrouterBilling": {"chargedTokens": 7},
        "comfyuiPromptId": "prompt-1",
        "comfyuiHistory": {"node": "done"},
    }
    row = {
        "id": "img-1",
        "user_id": "user-1",
        "url": "/api/media/image.webp",
        "thumbnail_url": "/api/media/thumb.webp",
        "mode": "edit",
        "provider": "openrouter",
        "prompt_original": "original",
        "prompt_translated": "translated",
        "settings_json": "serialized-settings",
        "width": 640,
        "height": 480,
        "is_favorite": 1,
        "created_at": "2026-07-14T05:00:00Z",
        "deleted_at": "deleted",
        "storage_tier": "archive",
    }
    monkeypatch.setattr(main.json, "loads", lambda raw: events.append(("json", raw)) or settings)
    monkeypatch.setattr(main, "_media_file_size_from_url", lambda url: events.append(("file", url)) or 321)
    monkeypatch.setattr(main, "_user_model_name", lambda raw: events.append(("display", raw)) or "Display")
    monkeypatch.setattr(
        main,
        "_gallery_model_info",
        lambda value, provider: events.append(("model", value, provider)) or {"fullName": "Full"},
    )
    monkeypatch.setattr(
        main,
        "_gallery_public_params",
        lambda **kwargs: events.append(("params", kwargs)) or [{"label": "A", "value": "B"}],
    )
    monkeypatch.setattr(main, "_row_get", lambda value, key: events.append(("row_get", key)) or value.get(key))

    result = main.row_to_image(row)

    assert result == {
        "id": "img-1",
        "userId": "user-1",
        "url": "/api/media/image.webp",
        "thumbnailUrl": "/api/media/thumb.webp",
        "mode": "edit",
        "provider": "openrouter",
        "promptOriginal": "original",
        "promptTranslated": "translated",
        "seed": 42,
        "width": 640,
        "height": 480,
        "modelProfile": "Display",
        "modelInfo": {"fullName": "Full"},
        "loras": ["lora-a"],
        "preset": "preset-a",
        "generationTimeMs": 1250,
        "tokenCost": 7,
        "openrouterBilling": {"chargedTokens": 7},
        "fileSizeBytes": 321,
        "publicParams": [{"label": "A", "value": "B"}],
        "isFavorite": True,
        "createdAt": "2026-07-14T05:00:00Z",
        "comfyuiPromptId": "prompt-1",
        "comfyuiHistory": {"node": "done"},
        "deletedAt": "deleted",
        "storageTier": "archive",
    }
    assert events == [
        ("json", "serialized-settings"),
        ("file", "/api/media/image.webp"),
        ("display", "provider/model"),
        ("model", settings, "openrouter"),
        (
            "params",
            {
                "image_id": "img-1",
                "mode": "edit",
                "provider": "openrouter",
                "width": 640,
                "height": 480,
                "url": "/api/media/image.webp",
                "created_at": "2026-07-14T05:00:00Z",
                "settings": settings,
            },
        ),
        ("row_get", "deleted_at"),
        ("row_get", "storage_tier"),
    ]


def test_row_to_image_preserves_empty_settings_prompt_and_storage_defaults() -> None:
    row = {
        "id": "img-empty",
        "user_id": "user-empty",
        "url": None,
        "thumbnail_url": None,
        "mode": None,
        "provider": None,
        "prompt_original": None,
        "prompt_translated": None,
        "settings_json": None,
        "width": None,
        "height": None,
        "is_favorite": 0,
        "created_at": None,
        "deleted_at": None,
        "storage_tier": "",
    }

    result = main.row_to_image(row)

    assert result["promptOriginal"] == result["promptTranslated"] == ""
    assert result["seed"] == result["generationTimeMs"] == 0
    assert result["loras"] == []
    assert result["isFavorite"] is False
    assert result["deletedAt"] is None
    assert result["storageTier"] == "original"
