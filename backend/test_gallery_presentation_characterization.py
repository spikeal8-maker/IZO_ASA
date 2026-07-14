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
        "fullName": "ИЗО Base · ИЗО / FLUX.2 Klein · выпуск: 2026",
        "providerName": "ИЗО / FLUX.2 Klein",
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
