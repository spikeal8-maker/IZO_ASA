from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def seed_fresh_usd_rub_exchange(main_module: Any) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    exchange = {
        "rate": 80.0,
        "currency": "USD",
        "base": "RUB",
        "source": "test-fixture",
        "sourceUrl": "test://exchange",
        "sourceDate": now.date().isoformat(),
        "fetchedAt": now.isoformat(),
        "fetched_date": now.date().isoformat(),
        "fallback": False,
    }
    main_module._save_setting("exchange_usd_rub", exchange)
    return exchange


def patch_openrouter_image_capabilities(monkeypatch: Any, main_module: Any) -> None:
    async def fake_capabilities(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
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

    monkeypatch.setattr(main_module, "fetch_openrouter_image_capabilities", fake_capabilities)


def patch_openrouter_catalog_refresh(monkeypatch: Any, main_module: Any) -> None:
    async def fake_refresh() -> dict[str, Any]:
        return main_module.openrouter_catalog_snapshot()

    monkeypatch.setattr(main_module, "_openrouter_catalog_refresh_task", None)
    monkeypatch.setattr(main_module, "refresh_openrouter_catalog", fake_refresh)
