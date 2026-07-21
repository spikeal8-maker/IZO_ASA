"""Characterization for the bot domain and its worker runtime (ARCH-BE-BOTS-001).

Commit 1 safety net: pins the exact bot route inventory (so the extraction
cannot change paths or count) and the worker-runtime contract — BotRuntime
owns only mutable worker state (health/tasks/diag/cache), provider config is
read on demand via a single dependency, and tokens never appear in repr or
snapshots. These tests must stay green unchanged through commits 2 and 3.
"""
from __future__ import annotations

import re

import main
from app.services.bot_workers import (
    BotRuntime,
    ProviderConfigSnapshot,
)
from app.services.polling_health import PollingHealthRegistry

BOT_ROUTE_PATTERN = re.compile(r"^/api/(telegram|max|bots|admin/bots|platforms)")

EXPECTED_BOT_ROUTES = {
    ("DELETE", "/api/admin/bots/max/token-v2"),
    ("DELETE", "/api/admin/bots/telegram/token-v2"),
    ("GET", "/api/admin/bots/config-v2"),
    ("GET", "/api/admin/bots/status-v2"),
    ("GET", "/api/bots/status"),
    ("GET", "/api/max/me"),
    ("GET", "/api/platforms"),
    ("GET", "/api/telegram/me"),
    ("POST", "/api/admin/bots/max/delete-webhook-v2"),
    ("POST", "/api/admin/bots/max/set-webhook-v2"),
    ("POST", "/api/admin/bots/max/verify-v2"),
    ("POST", "/api/admin/bots/max/webhook-secret-v2"),
    ("POST", "/api/admin/bots/telegram/configure-v2"),
    ("POST", "/api/admin/bots/telegram/delete-webhook-v2"),
    ("POST", "/api/admin/bots/telegram/set-webhook-v2"),
    ("POST", "/api/admin/bots/telegram/verify-v2"),
    ("POST", "/api/admin/bots/telegram/webhook-secret-v2"),
    ("POST", "/api/bots/local-command"),
    ("POST", "/api/max/poll-once"),
    ("POST", "/api/max/send-message"),
    ("POST", "/api/max/set-webhook"),
    ("POST", "/api/max/webhook"),
    ("POST", "/api/telegram/configure-bot"),
    ("POST", "/api/telegram/delete-webhook"),
    ("POST", "/api/telegram/poll-once"),
    ("POST", "/api/telegram/send-message"),
    ("POST", "/api/telegram/set-webhook"),
    ("POST", "/api/telegram/webhook"),
    ("PUT", "/api/admin/bots/config-v2"),
    ("PUT", "/api/admin/bots/max/token-v2"),
    ("PUT", "/api/admin/bots/telegram/token-v2"),
}


def _current_bot_routes() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for route in main.app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", "")
        if not methods or not BOT_ROUTE_PATTERN.search(path):
            continue
        for method in methods:
            if method in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                found.add((method, path))
    return found


def test_bot_route_inventory_is_stable() -> None:
    current = _current_bot_routes()
    assert current == EXPECTED_BOT_ROUTES, {
        "added": sorted(current - EXPECTED_BOT_ROUTES),
        "removed": sorted(EXPECTED_BOT_ROUTES - current),
    }
    assert len(current) == 31


def test_bot_runtime_owns_worker_state() -> None:
    runtime = main.BOT_RUNTIME
    assert isinstance(runtime, BotRuntime)
    assert isinstance(runtime.polling_health, PollingHealthRegistry)
    assert isinstance(runtime.polling_tasks, dict)
    assert isinstance(runtime.max_polling_diag, dict)
    assert isinstance(runtime.max_deep_link_cache, dict)
    # BotRuntime does NOT mirror provider config as mutable fields.
    assert not hasattr(runtime, "telegram")
    assert not hasattr(runtime, "max")


def test_provider_config_reflects_canonical_globals() -> None:
    telegram = main.BOT_RUNTIME.provider_config("telegram")
    assert isinstance(telegram, ProviderConfigSnapshot)
    assert telegram.mode == main.BOT_UPDATES_MODE
    assert telegram.polling_enabled == main.TELEGRAM_POLLING_ENABLED
    assert telegram.token_configured == bool(main.TELEGRAM_BOT_TOKEN)
    maximum = main.BOT_RUNTIME.provider_config("max")
    assert maximum.mode == main.MAX_UPDATES_MODE
    assert maximum.polling_enabled == main.MAX_POLLING_ENABLED
    assert maximum.token_configured == bool(main.MAX_BOT_TOKEN)
    assert maximum.api_base_url == main.MAX_API_BASE_URL
    try:
        main.BOT_RUNTIME.provider_config("unknown")
    except KeyError:
        pass
    else:  # pragma: no cover
        raise AssertionError("unknown provider must raise KeyError")


def test_tokens_never_appear_in_repr_or_snapshot() -> None:
    snap = ProviderConfigSnapshot(
        provider="telegram",
        mode="polling",
        polling_enabled=True,
        token="super-secret-token-value",
    )
    assert "super-secret-token-value" not in repr(snap)
    snapshot = str(main.BOT_RUNTIME.snapshot())
    assert main.TELEGRAM_BOT_TOKEN == "" or main.TELEGRAM_BOT_TOKEN not in snapshot
    assert main.MAX_BOT_TOKEN == "" or main.MAX_BOT_TOKEN not in snapshot
    assert "tokenConfigured" in snapshot
