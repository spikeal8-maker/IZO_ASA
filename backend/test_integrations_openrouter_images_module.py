from __future__ import annotations

import pytest

import main
from app.integrations.openrouter_images import (
    build_openrouter_image_request_plan,
    openrouter_descriptor_values,
    openrouter_ratio_size,
    requested_orientation,
)


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (1280, 720, "horizontal"),
        (720, 1280, "vertical"),
        (1024, 1024, "square"),
        (0, 0, "square"),
    ],
)
def test_requested_orientation_preserves_legacy_comparison(width, height, expected):
    assert requested_orientation(width, height) == expected


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (1280, 720, "16:9"),
        (1536, 1024, "3:2"),
        (1024, 1024, "1:1"),
        (0, 1024, "auto"),
        (1024, 0, "auto"),
    ],
)
def test_ratio_size_preserves_reduction_and_auto(width, height, expected):
    assert openrouter_ratio_size(width, height) == expected


@pytest.mark.parametrize(
    ("capability", "key", "expected"),
    [
        ({"parameterDescriptors": {"resolution": {"values": ["1K", 2]}}}, "resolution", ["1K", "2"]),
        ({"parameterDescriptors": {"resolution": {"values": "1K"}}}, "resolution", []),
        ({"parameterDescriptors": []}, "resolution", []),
        (None, "resolution", []),
    ],
)
def test_descriptor_values_preserve_filtering_and_string_conversion(capability, key, expected):
    assert openrouter_descriptor_values(capability, key) == expected


@pytest.mark.parametrize(
    ("prefix", "width", "height", "size", "billing_width", "billing_height", "strategy"),
    [
        ("openai/image", 1024, 1024, "1024x1024", 1024, 1024, "openai_supported_size"),
        ("openai/image", 1280, 720, "1536x1024", 1536, 1024, "openai_supported_size"),
        ("openai/image", 720, 1280, "1024x1536", 1024, 1536, "openai_supported_size"),
        ("recraft/image", 1024, 1024, "1024x1024", 1024, 1024, "recraft_safe_size"),
        ("recraft/image", 1280, 720, "1536x1024", 1536, 1024, "recraft_safe_size"),
        ("recraft/image", 720, 1280, "1024x1536", 1024, 1536, "recraft_safe_size"),
    ],
)
def test_provider_safe_sizes_preserve_orientation_mapping(
    prefix,
    width,
    height,
    size,
    billing_width,
    billing_height,
    strategy,
):
    assert build_openrouter_image_request_plan(prefix, width, height) == {
        "size": size,
        "billing_width": billing_width,
        "billing_height": billing_height,
        "strategy": strategy,
    }


@pytest.mark.parametrize(
    ("tier", "expected"),
    [("sd", "512"), ("hd", "1K"), ("full_hd", "2K"), ("unknown", "1K")],
)
def test_sourceful_plan_preserves_resolution_tier_mapping(tier, expected):
    assert build_openrouter_image_request_plan(
        "sourceful/image",
        1280,
        720,
        resolution_tier=tier,
    ) == {
        "size": "16:9",
        "resolution": expected,
        "billing_width": 1280,
        "billing_height": 720,
        "strategy": "sourceful_resolution_ratio",
    }


def test_sourceful_plan_drops_resolution_not_advertised_by_descriptor():
    plan = build_openrouter_image_request_plan(
        "sourceful/image",
        1280,
        720,
        {"parameterDescriptors": {"resolution": {"values": ["2K"]}}},
        resolution_tier="hd",
    )

    assert plan["resolution"] is None
    assert plan["size"] == "16:9"


def test_google_plan_without_capability_preserves_ratio_and_default_resolution():
    assert build_openrouter_image_request_plan("google/image", 0, 0, resolution_tier="hd") == {
        "aspect_ratio": "auto",
        "resolution": "1K",
        "billing_width": 1024,
        "billing_height": 1024,
        "strategy": "google_normalized_aspect_ratio",
    }


def test_descriptor_plan_preserves_supported_values_and_rejects_unsupported_values():
    supported = build_openrouter_image_request_plan(
        "provider/image",
        1280,
        720,
        {
            "parameterDescriptors": {
                "aspect_ratio": {"values": ["16:9"]},
                "resolution": {"values": ["1K"]},
            }
        },
        resolution_tier="hd",
    )
    unsupported = build_openrouter_image_request_plan(
        "provider/image",
        1280,
        720,
        {
            "parameterDescriptors": {
                "aspect_ratio": {"values": ["1:1"]},
                "resolution": {"values": ["2K"]},
            }
        },
        resolution_tier="hd",
    )

    assert supported == {
        "aspect_ratio": "16:9",
        "resolution": "1K",
        "billing_width": 1280,
        "billing_height": 720,
        "strategy": "openrouter_capability_descriptors",
    }
    assert unsupported == {
        "aspect_ratio": None,
        "resolution": None,
        "billing_width": 1280,
        "billing_height": 720,
        "strategy": "openrouter_capability_descriptors",
    }


def test_generic_plan_preserves_requested_size_and_zero_defaults():
    assert build_openrouter_image_request_plan("provider/image", 0, 0) == {
        "size": "1024x1024",
        "billing_width": 1024,
        "billing_height": 1024,
        "strategy": "requested_size",
    }


def test_main_request_plan_wrapper_applies_resolution_policy_and_delegates(monkeypatch):
    capability = {"parameterDescriptors": {}}
    expected = {"strategy": "sentinel"}
    captured: dict[str, object] = {}

    monkeypatch.setattr(main, "resolution_id_for_size", lambda width, height: "custom-resolution")
    monkeypatch.setattr(main, "RESOLUTION_BY_ID", {"custom-resolution": {"tier": "full_hd"}})

    def fake_plan(model_id, width, height, capability_value, *, resolution_tier):
        captured.update({
            "model_id": model_id,
            "width": width,
            "height": height,
            "capability": capability_value,
            "resolution_tier": resolution_tier,
        })
        return expected

    monkeypatch.setattr(main, "build_openrouter_image_request_plan", fake_plan)

    assert main.openrouter_image_request_plan("provider/image", 1600, 900, capability) is expected
    assert captured == {
        "model_id": "provider/image",
        "width": 1600,
        "height": 900,
        "capability": capability,
        "resolution_tier": "full_hd",
    }


def test_main_private_planning_wrappers_delegate(monkeypatch):
    capability = {"parameterDescriptors": {}}
    seen: list[tuple[object, ...]] = []

    monkeypatch.setattr(main, "requested_orientation", lambda width, height: seen.append(("orientation", width, height)) or "square")
    monkeypatch.setattr(main, "openrouter_ratio_size", lambda width, height: seen.append(("ratio", width, height)) or "1:1")
    monkeypatch.setattr(main, "openrouter_descriptor_values", lambda value, key: seen.append(("descriptors", value, key)) or ["1K"])

    assert main._requested_orientation(1, 1) == "square"
    assert main._openrouter_ratio_size(1, 1) == "1:1"
    assert main._openrouter_descriptor_values(capability, "resolution") == ["1K"]
    assert seen == [
        ("orientation", 1, 1),
        ("ratio", 1, 1),
        ("descriptors", capability, "resolution"),
    ]
