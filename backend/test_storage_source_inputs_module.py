"""Generation source normalization preserves legacy slot and role contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.storage.source_inputs import generation_source_inputs, source_role_label


def _request(**overrides):
    values = {
        "mode": "image_to_image",
        "inputImages": [],
        "inputImage1": None,
        "inputImage2": None,
        "canvas": None,
        "maskImage": None,
        "outpaintMask": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    ("role", "label"),
    [
        ("base", "Основа"),
        ("image", "Изображение"),
        ("reference", "Референс"),
        ("ref", "Референс"),
        ("pose", "Поза"),
        ("face", "Лицо"),
        ("target", "Основа"),
        ("source", "Источник"),
        ("style", "Стиль"),
        ("clothes", "Одежда"),
        ("clothing", "Одежда"),
        ("background", "Фон"),
        ("mask", "Маска"),
        ("canvas", "Холст"),
    ],
)
def test_source_role_labels(role: str, label: str):
    assert source_role_label(role, 4) == label


def test_source_role_label_fallbacks_are_mode_and_slot_aware():
    assert source_role_label(None, 1) == "Основа"
    assert source_role_label("unknown", 2, "faceswap") == "Лицо"
    assert source_role_label("unknown", 2, "try_on") == "Одежда"
    assert source_role_label("unknown", 3, "edit") == "Исходник 3"


def test_faceswap_try_on_canvas_and_mask_roles_keep_slot_order():
    faceswap = generation_source_inputs(
        _request(
            mode="faceswap",
            inputImage1="target-image",
            inputImage2="face-image",
            canvas="canvas-image",
            maskImage="mask-image",
            outpaintMask="ignored-outpaint-mask",
        )
    )
    try_on = generation_source_inputs(
        _request(mode="try_on", inputImage1="person", inputImage2="garment", outpaintMask="outpaint-mask")
    )

    assert [(item["slot"], item["role"], item["value"]) for item in faceswap] == [
        (1, "target", "target-image"),
        (2, "face", "face-image"),
        (3, "canvas", "canvas-image"),
        (4, "mask", "mask-image"),
    ]
    assert [(item["slot"], item["role"], item["value"]) for item in try_on] == [
        (1, "base", "person"),
        (2, "clothes", "garment"),
        (3, "mask", "outpaint-mask"),
    ]


def test_edit_inputs_are_sorted_defaulted_capped_then_deduplicated():
    shared_prefix = "x" * 500
    items = [
        SimpleNamespace(index=8, role="reference", image="eight"),
        SimpleNamespace(index=1, role="", image="one"),
        SimpleNamespace(index=3, role="reference", image=shared_prefix + "a"),
        SimpleNamespace(index=2, role=None, image=None),
        SimpleNamespace(index=4, role="reference", image=shared_prefix + "b"),
        SimpleNamespace(index=5, role="style", image="five"),
        SimpleNamespace(index=6, role="background", image="six"),
        SimpleNamespace(index=7, role="pose", image="seven"),
        SimpleNamespace(index=9, role="mask", image="nine"),
        SimpleNamespace(index=10, role="canvas", image="ten"),
    ]

    result = generation_source_inputs(_request(mode="edit", inputImages=items))

    assert [(item["slot"], item["role"]) for item in result] == [
        (1, "base"),
        (3, "reference"),
        (5, "style"),
        (6, "background"),
        (7, "pose"),
        (8, "reference"),
        (9, "mask"),
    ]
    assert all(item["slot"] != 10 for item in result)
