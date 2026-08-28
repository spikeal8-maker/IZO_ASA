from __future__ import annotations

import pytest

import main

from app.services.openrouter_image_economics import (
    NEW_IMAGE_PRICE_SPECS,
    actual_pricing_samples,
    comparable_actual_costs,
    estimate_live_image_cost,
)


def test_new_openrouter_image_catalog_contains_current_live_models():
    ids = {row["id"] for row in NEW_IMAGE_PRICE_SPECS}

    assert {
        "bytedance-seed/seedream-5-0-lite",
        "bytedance-seed/seedream-5-0-pro",
        "x-ai/grok-imagine-image-2.0",
        "qwen/qwen-image-3-pro",
        "qwen/qwen-image-3",
        "microsoft/mai-image-2.5-pro",
        "krea/krea-2-large",
        "krea/krea-2-medium",
        "krea/krea-2-medium-turbo",
    } <= ids
    assert ids <= set(main.OPENROUTER_PRICE_CATALOG)


def test_live_image_cost_selects_resolution_variant_and_input_fee():
    pricing = [
        {"billable": "output_image", "unit": "image", "cost_usd": 0.045},
        {"billable": "output_image", "unit": "image", "cost_usd": 0.09, "variant": "high_resolution"},
        {"billable": "input_image", "unit": "image", "cost_usd": 0.003},
    ]

    one_k = estimate_live_image_cost(pricing, megapixels=1, resolution="1K", input_image_count=1)
    two_k = estimate_live_image_cost(pricing, megapixels=2, resolution="2K", input_image_count=1)

    assert one_k is not None and one_k.cost_usd == pytest.approx(0.048)
    assert two_k is not None and two_k.cost_usd == pytest.approx(0.093)


def test_live_image_cost_uses_expensive_compatible_quality_when_ui_has_no_quality_selector():
    pricing = [
        {"billable": "input_image", "unit": "image", "cost_usd": 0.01},
        {"billable": "output_image", "unit": "image", "cost_usd": 0.04, "variant": "low_1k"},
        {"billable": "output_image", "unit": "image", "cost_usd": 0.06, "variant": "medium_1k"},
        {"billable": "output_image", "unit": "image", "cost_usd": 0.08, "variant": "medium_2k"},
    ]

    estimate = estimate_live_image_cost(pricing, megapixels=1, resolution="1K", input_image_count=1)

    assert estimate is not None
    assert estimate.cost_usd == pytest.approx(0.07)


def test_live_image_token_cost_includes_prompt_and_reference_estimates():
    pricing = [
        {"billable": "input_text", "unit": "token", "cost_usd": 0.000005},
        {"billable": "input_image", "unit": "token", "cost_usd": 0.000008},
        {"billable": "output_image", "unit": "token", "cost_usd": 0.000108},
    ]

    estimate = estimate_live_image_cost(pricing, megapixels=1, resolution=None, input_image_count=1)

    assert estimate is not None
    assert estimate.cost_usd == pytest.approx(0.000108 * 1300 + 0.000008 * 1300 + 0.000005 * 40)


def test_image_history_requires_exact_operation_dimensions_and_inputs():
    rows = [{
        "mode": "edit",
        "width": 1024,
        "height": 1024,
        "settings_json": {
            "openrouterModel": "vendor/model",
            "openrouterCostUsd": 0.12,
            "openrouterBilling": {"billingWidth": 1024, "billingHeight": 1024, "inputImageCount": 2},
        },
    }]
    samples = actual_pricing_samples(rows, lambda value: value)
    assert comparable_actual_costs(
        samples,
        model_id="vendor/model",
        mode="edit",
        billing_width=1024,
        billing_height=1024,
        input_image_count=2,
    ) == [0.12]
    assert comparable_actual_costs(
        samples,
        model_id="vendor/model",
        mode="edit",
        billing_width=1024,
        billing_height=1024,
        input_image_count=1,
    ) == []
