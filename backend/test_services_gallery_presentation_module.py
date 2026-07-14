from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

import app.services.gallery_presentation as gallery_presentation_module
from app.services.gallery_presentation import (
    gallery_aspect_ratio,
    gallery_model_info,
    gallery_mode_label,
    gallery_public_params,
    gallery_source_ids,
)


def test_gallery_presentation_module_is_import_safe_and_has_no_concrete_dependencies() -> None:
    source = inspect.getsource(gallery_presentation_module).lower()

    for forbidden in (
        "import main",
        "fastapi",
        "pydantic",
        "sqlite3",
        "pathlib",
        "httpx",
        "os.environ",
        "admin_models_page_cache",
    ):
        assert forbidden not in source


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [(1024, 1024, "1:1"), (1920, 1080, "16:9"), (768, 1024, "3:4"), (0, 10, None), (-10, 20, "-1:2")],
)
def test_aspect_ratio_contract(width, height, expected) -> None:
    assert gallery_aspect_ratio(width, height) == expected


def test_mode_label_preserves_aliases_lookup_whitespace_and_unknown_fallback() -> None:
    assert gallery_mode_label("text_to_image") == "По тексту"
    assert gallery_mode_label(" face_swap ") == "Лицо"
    assert gallery_mode_label(" custom ") == " custom "
    assert gallery_mode_label(None) == "По тексту"


def test_source_ids_preserve_alias_precedence_and_slice_before_filter() -> None:
    settings = {
        "sourceImageIds": [None, "first", "", " second ", "ignored"],
        "source_image_ids": ["fallback"],
        "sourceIds": ["last"],
    }

    assert gallery_source_ids(settings) == ["first", " second "]
    assert gallery_source_ids({"source_image_ids": [1, 2]}) == ["1", "2"]
    assert gallery_source_ids({"sourceIds": ["last"]}) == ["last"]


@pytest.mark.parametrize("value", ["not-a-list", {"id": "x"}, 42, None])
def test_source_ids_reject_non_list_values(value) -> None:
    assert gallery_source_ids({"sourceImageIds": value}) == []


def test_model_info_maps_local_models_to_exact_izo_payload() -> None:
    assert gallery_model_info(
        {"modelProfile": "local_flux_v2"},
        "provider",
        price_catalog={},
        release_years={},
        model_display_name=lambda raw: f"display:{raw}",
    ) == {
        "shortName": "ИЗО Base",
        "fullName": "ИЗО Base · ИЗО / FLUX.2 Klein · выпуск: 2026",
        "providerName": "ИЗО / FLUX.2 Klein",
        "release": "2026",
    }


def test_model_info_preserves_billing_catalog_release_and_raw_precedence() -> None:
    result = gallery_model_info(
        {
            "modelProfile": "profile/model",
            "openrouterModel": "ignored/model",
            "openrouterBilling": {"modelName": "Billing Name", "modelProvider": "Billing Maker"},
        },
        "ignored-provider",
        price_catalog={"profile/model": SimpleNamespace(name="Catalog Name", provider="Catalog Maker")},
        release_years={"profile/model": "2025"},
        model_display_name=lambda raw: f"display:{raw}",
    )

    assert result == {
        "shortName": "Billing Name",
        "fullName": "Billing Name · Billing Maker · выпуск: 2025",
        "providerName": "Billing Maker",
        "release": "2025",
    }


def test_model_info_uses_catalog_then_display_callback_and_ignores_non_dict_billing() -> None:
    catalog = gallery_model_info(
        {"modelProfile": "catalog/model"},
        None,
        price_catalog={"catalog/model": SimpleNamespace(name="Catalog", provider="Maker")},
        release_years={},
        model_display_name=lambda raw: f"display:{raw}",
    )
    fallback = gallery_model_info(
        {"openrouterModel": "fallback/model", "openrouterBilling": "invalid"},
        None,
        price_catalog={},
        release_years={},
        model_display_name=lambda raw: f"display:{raw}",
    )

    assert catalog["shortName"] == "Catalog"
    assert catalog["providerName"] == "Maker"
    assert fallback["shortName"] == "display:fallback/model"
    assert fallback["providerName"] == ""


def test_public_params_preserve_order_values_and_callback_sequence() -> None:
    events: list[tuple[object, ...]] = []
    settings = {"generationTimeMs": 900}

    result = gallery_public_params(
        mode="edit",
        provider="openrouter",
        width=640,
        height=480,
        url="/api/media/item.webp",
        created_at="created",
        settings=settings,
        model_info=lambda value, provider: events.append(("model", value, provider)) or {"fullName": "Full"},
        token_cost=lambda value: events.append(("tokens", value)) or 3,
        aspect_ratio=lambda width, height: events.append(("aspect", width, height)) or "4:3",
        media_file_size=lambda url: events.append(("file_size", url)) or 1024,
        format_bytes=lambda value: events.append(("bytes", value)) or "1,0 КБ",
        format_duration=lambda value: events.append(("duration", value)) or "900 мс",
        format_datetime=lambda value: events.append(("datetime", value)) or "Date",
        mode_label=lambda value: events.append(("mode", value)) or "Сборка",
    )

    assert result == [
        {"label": "Токены", "value": "3 ток."},
        {"label": "Разрешение", "value": "640×480"},
        {"label": "Формат", "value": "4:3"},
        {"label": "Вес файла", "value": "1,0 КБ"},
        {"label": "Время генерации", "value": "900 мс"},
        {"label": "Дата генерации", "value": "Date"},
        {"label": "Режим", "value": "Сборка"},
        {"label": "Полное наименование модели", "value": "Full"},
    ]
    assert events == [
        ("model", settings, "openrouter"),
        ("tokens", settings),
        ("tokens", settings),
        ("aspect", 640, 480),
        ("file_size", "/api/media/item.webp"),
        ("bytes", 1024),
        ("duration", 900),
        ("datetime", "created"),
        ("mode", "edit"),
    ]


def test_public_params_filter_falsy_values_but_keep_zero_token_cost() -> None:
    common = {
        "mode": None,
        "provider": None,
        "width": 0,
        "height": 0,
        "url": None,
        "created_at": None,
        "settings": {},
        "model_info": lambda settings, provider: {"fullName": ""},
        "aspect_ratio": lambda width, height: None,
        "media_file_size": lambda url: None,
        "format_bytes": lambda value: None,
        "format_duration": lambda value: None,
        "format_datetime": lambda value: None,
        "mode_label": lambda value: "",
    }

    empty = gallery_public_params(token_cost=lambda settings: None, **common)
    zero = gallery_public_params(token_cost=lambda settings: 0, **common)

    assert empty == []
    assert zero == [{"label": "Токены", "value": "0 ток."}]
