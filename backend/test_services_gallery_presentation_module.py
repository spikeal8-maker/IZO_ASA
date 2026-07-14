from __future__ import annotations

import inspect

import pytest

import app.services.gallery_presentation as gallery_presentation_module
from app.services.gallery_presentation import (
    gallery_aspect_ratio,
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
