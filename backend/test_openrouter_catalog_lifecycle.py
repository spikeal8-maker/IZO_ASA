import asyncio

from app.integrations.openrouter_catalog import (
    DAILY_REFRESH_SECONDS,
    DailyCatalogWorker,
    build_catalog_lifecycle,
    live_image_output_rate,
)


def test_daily_refresh_interval_is_exactly_one_day():
    assert DAILY_REFRESH_SECONDS == 86_400


def test_live_image_output_rate_requires_explicit_positive_provider_price():
    assert live_image_output_rate({"pricing": {"image_output": "0.000108"}}) == (
        "token_estimate",
        0.000108,
    )
    assert live_image_output_rate({"pricing": {"prompt": "0", "completion": "0"}}) is None
    assert live_image_output_rate({"pricing": {}}) is None


def test_catalog_lifecycle_reports_add_remove_price_change_and_unpriced():
    previous = build_catalog_lifecycle(
        [{"id": "image/old", "pricing": {"image_output": "0.1"}}],
        [{"id": "video/a", "pricingSkus": {"duration_seconds": 0.2}}],
        refreshed_at="2026-07-23T00:00:00+00:00",
    )
    current = build_catalog_lifecycle(
        [
            {"id": "image/new", "pricing": {}},
            {"id": "image/priced", "pricing": {"image_output": "0.05"}},
        ],
        [{"id": "video/a", "pricingSkus": {"duration_seconds": 0.3}}],
        previous,
        refreshed_at="2026-07-24T00:00:00+00:00",
    )

    assert current["changes"]["images"] == {
        "added": ["image/new", "image/priced"],
        "removed": ["image/old"],
        "priceChanged": [],
        "unpriced": ["image/new"],
    }
    assert current["changes"]["videos"]["priceChanged"] == ["video/a"]


def test_effective_price_catalog_adds_only_explicit_live_prices(monkeypatch):
    import main

    monkeypatch.setitem(
        main._openrouter_capability_cache,
        "models",
        [
            {
                "id": "provider/live-priced",
                "name": "Live Priced",
                "providerName": "Provider",
                "pricing": {"image_output": "0.000108"},
            },
            {
                "id": "provider/live-unpriced",
                "name": "Live Unpriced",
                "pricing": {"prompt": "0", "completion": "0"},
            },
        ],
    )

    catalog = main.openrouter_effective_price_catalog()
    assert catalog["provider/live-priced"].pricing_type == "token_estimate"
    assert catalog["provider/live-priced"].usd == 0.000108
    assert catalog["provider/live-priced"].source == "openrouter_live_catalog"
    assert "provider/live-unpriced" not in catalog


def test_daily_worker_has_one_owner_and_stops_cleanly():
    async def run() -> None:
        worker = DailyCatalogWorker()
        refreshed = asyncio.Event()
        errors: list[Exception] = []

        async def refresh() -> None:
            refreshed.set()

        assert worker.start(
            load_lifecycle=lambda: {},
            key_configured=lambda: True,
            refresh=refresh,
            report_error=errors.append,
        ) is True
        assert worker.start(
            load_lifecycle=lambda: {},
            key_configured=lambda: True,
            refresh=refresh,
            report_error=errors.append,
        ) is False
        await asyncio.wait_for(refreshed.wait(), timeout=1)
        await worker.stop()
        assert worker.task is None
        assert errors == []

    asyncio.run(run())
