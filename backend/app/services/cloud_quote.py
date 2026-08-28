"""Pure cloud-product quote calculation used in shadow and settlement paths.

The accepted quote is a snapshot: later provider usage may calibrate a future
quote, but it must never increase the charge already shown to a user.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from statistics import fmean
from typing import Any, Callable, Iterable


def _positive(values: Iterable[Any]) -> list[float]:
    result: list[float] = []
    for raw in values:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value > 0:
            result.append(value)
    return result


def percentile_nearest_rank(values: Iterable[Any], percentile: float) -> float | None:
    samples = sorted(_positive(values))
    if not samples:
        return None
    rank = max(1, math.ceil(max(0.0, min(1.0, percentile)) * len(samples)))
    return samples[rank - 1]


def build_cloud_quote(
    *,
    official_cost_usd: float | None,
    comparable_actual_costs_usd: Iterable[Any] = (),
    provider_minimum_usd: float | None = None,
    exchange_rate: float,
    funding_reserve_percent: float,
    minimum_margin_percent: float,
    token_rub: float,
    minimum_tokens: float = 1,
    token_quantum: float = 1,
    official_source: str = "provider_catalog",
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Return a conservative, fully sourced quote without mutating balances."""

    actual = _positive(comparable_actual_costs_usd)
    last_actual = actual[0] if actual else None
    mean_actual = fmean(actual) if actual else None
    p90_actual = percentile_nearest_rank(actual, 0.90)
    candidates = {
        official_source: _positive([official_cost_usd]),
        "last_comparable_actual": _positive([last_actual]),
        "mean_comparable_actual": _positive([mean_actual]),
        "p90_comparable_actual": _positive([p90_actual]),
        "provider_minimum": _positive([provider_minimum_usd]),
    }
    flattened = [(source, values[0]) for source, values in candidates.items() if values]
    if not flattened:
        raise ValueError("A cloud quote requires at least one positive USD cost source.")
    source, cost_usd = max(flattened, key=lambda item: item[1])
    usd_rub = max(0.000001, float(exchange_rate))
    reserve_percent = max(0.0, float(funding_reserve_percent))
    effective_usd_rub = usd_rub * (1 + reserve_percent / 100)
    cost_rub = cost_usd * effective_usd_rub
    margin_percent = max(0.0, min(95.0, float(minimum_margin_percent)))
    margin_factor = 1 - margin_percent / 100
    required_revenue = cost_rub / margin_factor
    rub_per_token = max(0.01, float(token_rub))
    quantum = max(0.001, float(token_quantum))
    tokens_value = max(float(minimum_tokens), math.ceil(required_revenue / rub_per_token / quantum) * quantum)
    tokens: int | float = int(tokens_value) if quantum >= 1 else round(tokens_value, 3)
    revenue_rub = tokens * rub_per_token
    profit_rub = revenue_rub - cost_rub
    actual_margin = profit_rub / revenue_rub * 100 if revenue_rub else None
    markup = profit_rub / cost_rub * 100 if cost_rub else None
    sample_count = len(actual)
    confidence = "high" if sample_count >= 10 and official_cost_usd else "medium" if sample_count >= 3 or official_cost_usd else "low"
    return {
        "schema": "cloud-quote-v1",
        "mode": "shadow",
        "observedAt": observed_at or datetime.now(timezone.utc).isoformat(),
        "selectedSource": source,
        "confidence": confidence,
        "sampleCount": sample_count,
        "officialCostUsd": round(float(official_cost_usd), 8) if _positive([official_cost_usd]) else None,
        "lastActualCostUsd": round(last_actual, 8) if last_actual is not None else None,
        "meanActualCostUsd": round(mean_actual, 8) if mean_actual is not None else None,
        "p90ActualCostUsd": round(p90_actual, 8) if p90_actual is not None else None,
        "providerMinimumUsd": round(float(provider_minimum_usd), 8) if _positive([provider_minimum_usd]) else None,
        "quotedCostUsd": round(cost_usd, 8),
        "exchangeRate": round(usd_rub, 6),
        "fundingReservePercent": round(reserve_percent, 4),
        "effectiveUsdRub": round(effective_usd_rub, 6),
        "quotedCostRub": round(cost_rub, 6),
        "minimumMarginPercent": round(margin_percent, 4),
        "equivalentMarkupPercent": round(margin_percent / margin_factor, 4),
        "tokenRub": round(rub_per_token, 6),
        "reservedTokens": tokens,
        "requiredRevenueRub": round(required_revenue, 6),
        "revenueRub": round(revenue_rub, 6),
        "profitRub": round(profit_rub, 6),
        "marginPercent": round(actual_margin, 4) if actual_margin is not None else None,
        "markupPercent": round(markup, 4) if markup is not None else None,
    }


def build_legacy_shadow_quote(*, legacy_reserved_tokens: int | float, **quote_inputs: Any) -> dict[str, Any]:
    """Attach the active reservation comparison to a shadow quote."""

    quote = build_cloud_quote(**quote_inputs)
    quote["legacyReservedTokens"] = legacy_reserved_tokens
    quote["tokenDelta"] = round(float(quote["reservedTokens"]) - float(legacy_reserved_tokens), 3)
    return quote


def finalize_legacy_billing_snapshot(
    snapshot: dict[str, Any],
    actual_cost_usd: float | None,
    *,
    minimum_tokens: int,
    default_token_rub: float,
    default_margin_percent: float,
    tokens_for_cost: Callable[[float, int, dict[str, Any]], int],
) -> dict[str, Any]:
    """Enrich the immutable accepted reservation with actual provider cost."""

    result = dict(snapshot or {})
    if isinstance(result.get("shadowQuote"), dict):
        result["shadowQuote"] = finalize_shadow_quote(result["shadowQuote"], actual_cost_usd)
    if actual_cost_usd is None:
        result["billingStatus"] = "actual_cost_missing"
        return result
    effective_rate = result.get("effectiveUsdRub")
    economy = {
        "tokenRub": result.get("tokenRub", default_token_rub),
        "minMarginPercent": result.get("minMarginPercent", default_margin_percent),
    }
    try:
        actual_rub = float(actual_cost_usd) * float(effective_rate)
        actual_tokens = tokens_for_cost(actual_rub, minimum_tokens, economy)
        charged_tokens = int(result.get("chargedTokens") or 0)
        revenue_rub = charged_tokens * float(economy["tokenRub"])
        profit_rub = revenue_rub - actual_rub
        result.update({
            "billingStatus": "actual", "actualCostUsd": round(float(actual_cost_usd), 6),
            "actualCostRub": round(actual_rub, 4), "actualTokens": actual_tokens,
            "chargedTokens": charged_tokens, "tokenDelta": charged_tokens - actual_tokens,
            "revenueRub": round(revenue_rub, 4), "profitRub": round(profit_rub, 4),
            "marginPercent": round((profit_rub / revenue_rub) * 100, 2) if revenue_rub > 0 else None,
        })
    except (TypeError, ValueError):
        result["billingStatus"] = "actual_cost_unpriced"
    return result


def finalize_shadow_quote(quote: dict[str, Any], actual_cost_usd: float | None) -> dict[str, Any]:
    result = dict(quote or {})
    costs = _positive([actual_cost_usd])
    if not costs:
        result["actualStatus"] = "missing"
        return result
    actual_usd = costs[0]
    effective_rate = float(result.get("effectiveUsdRub") or 0)
    revenue_rub = float(result.get("revenueRub") or 0)
    actual_rub = actual_usd * effective_rate
    profit_rub = revenue_rub - actual_rub
    margin = profit_rub / revenue_rub * 100 if revenue_rub else None
    required_margin = float(result.get("minimumMarginPercent") or 0)
    result.update({
        "actualStatus": "priced",
        "actualCostUsd": round(actual_usd, 8),
        "actualCostRub": round(actual_rub, 6),
        "actualProfitRub": round(profit_rub, 6),
        "actualMarginPercent": round(margin, 4) if margin is not None else None,
        "underquoted": actual_usd > float(result.get("quotedCostUsd") or 0),
        "belowMinimumMargin": margin is not None and margin < required_margin,
    })
    return result


def summarize_shadow_quotes(quotes: Iterable[Any]) -> dict[str, Any]:
    rows = [row for row in quotes if isinstance(row, dict) and row.get("schema") == "cloud-quote-v1"]
    priced = [row for row in rows if row.get("actualStatus") == "priced"]
    margins: list[float] = []
    for row in priced:
        try:
            margin = float(row.get("actualMarginPercent"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(margin):
            margins.append(margin)
    return {
        "quoted": len(rows),
        "priced": len(priced),
        "missingActual": len(rows) - len(priced),
        "underquoted": sum(1 for row in priced if row.get("underquoted") is True),
        "belowMinimumMargin": sum(1 for row in priced if row.get("belowMinimumMargin") is True),
        "averageActualMarginPercent": round(fmean(margins), 4) if margins else None,
        "alert": sum(1 for row in priced[:5] if row.get("belowMinimumMargin") is True) >= 3,
    }
