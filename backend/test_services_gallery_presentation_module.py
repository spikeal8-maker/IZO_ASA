from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

import app.services.gallery_presentation as gallery_presentation_module
from app.services.gallery_presentation import (
    gallery_aspect_ratio,
    gallery_model_info,
    gallery_mode_label,
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
