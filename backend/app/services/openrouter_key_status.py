"""Pure controller for OpenRouter credential status and explicit read-only probe."""
from __future__ import annotations

import hashlib
import time
from collections.abc import Awaitable, Callable
from typing import Any

from ..security.secret_store import SecretStoreError


async def collect_openrouter_key_status(
    *,
    force: bool,
    cache: dict[str, Any],
    ttl_seconds: float,
    get_key: Callable[[], str],
    get_source: Callable[[], str],
    store_ready: Callable[[], bool],
    attach: Callable[[dict[str, Any]], dict[str, Any]],
    probe: Callable[..., Awaitable[dict[str, Any]]],
    base_url: str,
    headers: Callable[[], dict[str, str]],
) -> dict[str, Any]:
    now = time.monotonic()
    try:
        key = get_key()
        source = get_source()
    except SecretStoreError:
        return attach({
            "configured": False, "keyConfigured": False, "secretStoreReady": False,
            "liveVerified": False, "ok": False, "error": "SECRET_STORE_UNAVAILABLE",
        })
    key_marker = hashlib.sha256((source + "\0" + key).encode()).hexdigest()[:16] if key else ""
    cached = cache.get("data")
    if (not force and isinstance(cached, dict)
            and cache.get("keyMarker") == key_marker
            and now - float(cache.get("ts") or 0) < ttl_seconds):
        return dict(cached)
    if not key:
        result = attach({
            "configured": False, "keyConfigured": False,
            "secretStoreReady": store_ready(), "liveVerified": False,
            "ok": False, "error": "OPENROUTER_KEY_NOT_CONFIGURED",
        })
        cache.update({"ts": now, "data": result, "keyMarker": key_marker})
        return dict(result)
    if not force:
        return attach({
            "configured": True, "keyConfigured": True,
            "secretStoreReady": store_ready(), "liveVerified": False,
            "source": source, "ok": False, "pending": True, "error": None,
        })
    try:
        detail = await probe(
            base_url=base_url, key_headers=headers(), credits_headers=headers(),
            timeout_seconds=15,
        )
        result = attach({
            "configured": True, "keyConfigured": True,
            "secretStoreReady": store_ready(), "liveVerified": detail.get("ok") is True,
            "source": source, **detail,
        })
    except Exception:
        result = attach({
            "configured": True, "keyConfigured": True,
            "secretStoreReady": store_ready(), "liveVerified": False,
            "source": source, "ok": False, "error": "OPENROUTER_NETWORK_UNAVAILABLE",
        })
    cache.update({"ts": now, "data": result, "keyMarker": key_marker})
    return dict(result)
