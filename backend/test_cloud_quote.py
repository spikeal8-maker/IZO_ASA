from __future__ import annotations

import pytest

from app.services.cloud_quote import build_cloud_quote, finalize_shadow_quote, percentile_nearest_rank, summarize_shadow_quotes


def test_cloud_quote_selects_conservative_comparable_p90_and_true_margin() -> None:
    quote = build_cloud_quote(
        official_cost_usd=1.0,
        comparable_actual_costs_usd=[1.1, 1.4, 0.9, 1.2, 1.3],
        provider_minimum_usd=0.5,
        exchange_rate=80,
        funding_reserve_percent=30,
        minimum_margin_percent=50,
        token_rub=5,
        observed_at="2026-08-28T00:00:00+00:00",
    )
    assert quote["selectedSource"] == "p90_comparable_actual"
    assert quote["quotedCostUsd"] == 1.4
    assert quote["effectiveUsdRub"] == 104
    assert quote["equivalentMarkupPercent"] == 100
    assert quote["reservedTokens"] == 59
    assert quote["marginPercent"] >= 50


def test_cloud_quote_uses_official_cost_without_history_and_reports_confidence() -> None:
    quote = build_cloud_quote(
        official_cost_usd=0.04,
        exchange_rate=84,
        funding_reserve_percent=30,
        minimum_margin_percent=40,
        token_rub=5,
    )
    assert quote["selectedSource"] == "provider_catalog"
    assert quote["sampleCount"] == 0
    assert quote["confidence"] == "medium"
    assert quote["reservedTokens"] == 2


def test_cloud_quote_rejects_missing_price_and_percentile_uses_nearest_rank() -> None:
    assert percentile_nearest_rank([1, 2, 3, 4], 0.90) == 4
    with pytest.raises(ValueError):
        build_cloud_quote(
            official_cost_usd=None,
            exchange_rate=84,
            funding_reserve_percent=30,
            minimum_margin_percent=50,
            token_rub=5,
        )


def test_shadow_finalization_reports_underquote_and_repeated_margin_alert() -> None:
    quote = build_cloud_quote(
        official_cost_usd=1,
        exchange_rate=80,
        funding_reserve_percent=0,
        minimum_margin_percent=50,
        token_rub=5,
    )
    failed_margin = finalize_shadow_quote(quote, 1.6)
    assert failed_margin["underquoted"] is True
    assert failed_margin["belowMinimumMargin"] is True
    summary = summarize_shadow_quotes([failed_margin, failed_margin, failed_margin, quote])
    assert summary == {
        "quoted": 4,
        "priced": 3,
        "missingActual": 1,
        "underquoted": 3,
        "belowMinimumMargin": 3,
        "averageActualMarginPercent": 20.0,
        "alert": True,
    }
