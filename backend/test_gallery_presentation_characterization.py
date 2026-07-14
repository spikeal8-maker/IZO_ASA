from __future__ import annotations

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
