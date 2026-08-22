"""OpenRouter image catalogue additions and endpoint-aware cost estimates.

The provider's image catalogue changes independently of application releases.
Static rows below are conservative fallbacks that make a live catalogue model
billable in the admin UI.  Whenever an endpoint publishes structured pricing,
``estimate_live_image_cost`` is the authoritative quote source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


SHORT_PROMPT_TEXT_TOKENS = 40
OUTPUT_IMAGE_TOKENS_1MP = 1300


NEW_IMAGE_PRICE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "bytedance-seed/seedream-5-0-lite",
        "name": "Seedream 5.0 Lite",
        "provider": "ByteDance Seed",
        "pricing_type": "image",
        "usd": 0.035,
        "min_tokens": 1,
        "source": "openrouter_endpoint_2026-08-22",
    },
    {
        "id": "bytedance-seed/seedream-5-0-pro",
        "name": "Seedream 5.0 Pro",
        "provider": "ByteDance Seed",
        "pricing_type": "image",
        "usd": 0.09,
        "min_tokens": 3,
        "source": "openrouter_endpoint_2026-08-22",
    },
    {
        "id": "x-ai/grok-imagine-image-2.0",
        "name": "Grok Imagine Image 2.0",
        "provider": "xAI",
        "pricing_type": "image",
        "usd": 0.08,
        "min_tokens": 3,
        "source": "openrouter_endpoint_2026-08-22",
    },
    {
        "id": "qwen/qwen-image-3-pro",
        "name": "Qwen Image 3 Pro",
        "provider": "Alibaba Cloud",
        "pricing_type": "image",
        "usd": 0.075,
        "min_tokens": 3,
        "source": "openrouter_endpoint_2026-08-22",
    },
    {
        "id": "qwen/qwen-image-3",
        "name": "Qwen Image 3",
        "provider": "Alibaba Cloud",
        "pricing_type": "image",
        "usd": 0.03,
        "min_tokens": 1,
        "source": "openrouter_endpoint_2026-08-22",
    },
    {
        "id": "microsoft/mai-image-2.5-pro",
        "name": "MAI-Image-2.5 Pro",
        "provider": "Microsoft",
        "pricing_type": "token_estimate",
        "usd": 0.000108,
        "min_tokens": 3,
        "source": "openrouter_endpoint_2026-08-22",
    },
    {
        "id": "krea/krea-2-large",
        "name": "Krea 2 Large",
        "provider": "Krea",
        "pricing_type": "token_estimate",
        "usd": 0.0000143712574850299,
        "min_tokens": 1,
        "source": "openrouter_models_2026-08-22",
    },
    {
        "id": "krea/krea-2-medium",
        "name": "Krea 2 Medium",
        "provider": "Krea",
        "pricing_type": "token_estimate",
        "usd": 0.00000718562874251497,
        "min_tokens": 1,
        "source": "openrouter_models_2026-08-22",
    },
    {
        "id": "krea/krea-2-medium-turbo",
        "name": "Krea 2 Medium Turbo",
        "provider": "Krea",
        "pricing_type": "token_estimate",
        "usd": 0.00000359281437125749,
        "min_tokens": 1,
        "source": "openrouter_models_2026-08-22",
    },
)


@dataclass(frozen=True)
class LiveImageEstimate:
    cost_usd: float
    source_keys: tuple[str, ...]


def _money(value: Any) -> float | None:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if amount >= 0 else None


def _normalized_resolution(value: Any) -> str:
    text = str(value or "").strip().lower().replace(" ", "")
    return text.replace("high_resolution", "2k")


def _select_output_image_row(
    rows: list[dict[str, Any]],
    resolution: str | None,
) -> dict[str, Any] | None:
    if not rows:
        return None
    normalized = _normalized_resolution(resolution)
    base = [row for row in rows if not str(row.get("variant") or "").strip()]
    variants = [row for row in rows if str(row.get("variant") or "").strip()]
    if normalized:
        exact = [
            row for row in variants
            if normalized in _normalized_resolution(row.get("variant"))
        ]
        if exact:
            return max(exact, key=lambda row: _money(row.get("cost_usd")) or 0.0)
        if normalized in {"2k", "4k"}:
            high = [row for row in variants if "high_resolution" in str(row.get("variant") or "").lower()]
            if high:
                return max(high, key=lambda row: _money(row.get("cost_usd")) or 0.0)
    if base:
        return max(base, key=lambda row: _money(row.get("cost_usd")) or 0.0)
    # Some endpoints (for example Grok) only publish quality/resolution
    # variants.  The product does not expose that provider quality selector,
    # therefore use the most expensive compatible output instead of quoting
    # below a possible provider charge.
    return max(variants, key=lambda row: _money(row.get("cost_usd")) or 0.0) if variants else None


def estimate_live_image_cost(
    pricing: Iterable[Any],
    *,
    megapixels: float,
    resolution: str | None,
    input_image_count: int,
) -> LiveImageEstimate | None:
    """Estimate one output from structured endpoint pricing.

    The calculation includes output, prompt-token and reference-image charges.
    Token-priced input images use the same conservative 1MP token estimate as
    output images because OpenRouter does not expose their token count before a
    generation completes.
    """

    rows = [row for row in pricing if isinstance(row, dict)]
    output_rows = [row for row in rows if str(row.get("billable") or "") == "output_image"]
    selected = _select_output_image_row(output_rows, resolution)
    if selected is None:
        return None
    selected_cost = _money(selected.get("cost_usd"))
    unit = str(selected.get("unit") or "").lower()
    if selected_cost is None:
        return None
    mp = max(1.0, float(megapixels or 0))
    if unit == "image":
        total = selected_cost
    elif unit in {"megapixel", "mp"}:
        total = selected_cost * mp
    elif unit == "token":
        total = selected_cost * OUTPUT_IMAGE_TOKENS_1MP * mp
    else:
        return None

    keys = [f"output_image:{unit}:{selected.get('variant') or 'default'}"]
    inputs = max(0, int(input_image_count or 0))
    for row in rows:
        billable = str(row.get("billable") or "")
        row_unit = str(row.get("unit") or "").lower()
        row_cost = _money(row.get("cost_usd"))
        if row_cost is None:
            continue
        if billable == "input_text" and row_unit == "token":
            total += row_cost * SHORT_PROMPT_TEXT_TOKENS
            keys.append("input_text:token")
        elif billable == "input_image" and inputs:
            if row_unit == "image":
                total += row_cost * inputs
                keys.append("input_image:image")
            elif row_unit == "token":
                total += row_cost * OUTPUT_IMAGE_TOKENS_1MP * mp * inputs
                keys.append("input_image:token_estimate")
    return LiveImageEstimate(cost_usd=total, source_keys=tuple(keys))
