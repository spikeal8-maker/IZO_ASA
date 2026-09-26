from __future__ import annotations

from datetime import datetime, timezone

import pytest


ADMIN_STATUS = "backend/test_admin_v2.py::test_admin_openrouter_status_without_key"
ADMIN_KEY = "backend/test_admin_v2.py::test_admin_can_save_openrouter_key_without_exposing_secret"
PRODUCT_DEFAULTS = "backend/test_product_consistency_20e2b.py::test_tariff_defaults_and_admin_settings_normalize"
PRODUCT_PERSIST = "backend/test_product_consistency_20e2b.py::test_tariff_settings_persist_and_read_from_admin_settings"

EXCHANGE_NODES = {ADMIN_STATUS, ADMIN_KEY, PRODUCT_DEFAULTS, PRODUCT_PERSIST}
CAPABILITY_NODES = {PRODUCT_DEFAULTS, PRODUCT_PERSIST}


def _normalized_nodeid(nodeid: str) -> str:
    return nodeid.replace("\\", "/")


@pytest.fixture(autouse=True)
def deterministic_provider_test_fakes(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    nodeid = _normalized_nodeid(request.node.nodeid)
    if nodeid not in EXCHANGE_NODES | CAPABILITY_NODES | {ADMIN_KEY}:
        yield
        return

    import main

    if nodeid in EXCHANGE_NODES:
        request.getfixturevalue("temp_db")
        now = datetime.now(timezone.utc)
        main._save_setting(
            "exchange_usd_rub",
            {
                "rate": 80.0,
                "currency": "USD",
                "base": "RUB",
                "source": "test-fixture",
                "sourceUrl": "test://exchange",
                "sourceDate": now.date().isoformat(),
                "fetchedAt": now.isoformat(),
                "fetched_date": now.date().isoformat(),
                "fallback": False,
            },
        )

    if nodeid in CAPABILITY_NODES:
        async def fake_capabilities(*_args, **_kwargs):
            return [
                {
                    "id": "black-forest-labs/flux.2-pro",
                    "modes": ["text_to_image"],
                    "supportedResolutionIds": ["sq-hd"],
                    "maxInputReferences": 2,
                },
                {
                    "id": "black-forest-labs/flux.2-max",
                    "modes": ["text_to_image"],
                    "supportedResolutionIds": ["sq-hd"],
                    "maxInputReferences": 2,
                },
            ]

        monkeypatch.setattr(main, "fetch_openrouter_image_capabilities", fake_capabilities)

    if nodeid == ADMIN_KEY:
        async def fake_refresh():
            return main.openrouter_catalog_snapshot()

        monkeypatch.setattr(main, "_openrouter_catalog_refresh_task", None)
        monkeypatch.setattr(main, "refresh_openrouter_catalog", fake_refresh)

    yield
