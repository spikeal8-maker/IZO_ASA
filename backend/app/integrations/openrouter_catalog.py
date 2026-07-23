"""Durable OpenRouter catalog lifecycle helpers.

The live provider catalog is discovery data, not an allowlist.  These helpers
build a compact persisted snapshot, report changes, and derive a conservative
image-output rate only when OpenRouter publishes one explicitly.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable


DAILY_REFRESH_SECONDS = 24 * 60 * 60


class DailyCatalogWorker:
    """Single-owner hourly wake-up for a durable once-per-day refresh."""

    def __init__(self) -> None:
        self.task: asyncio.Task[Any] | None = None

    def start(
        self,
        *,
        load_lifecycle: Callable[[], dict[str, Any]],
        key_configured: Callable[[], bool],
        refresh: Callable[[], Awaitable[Any]],
        report_error: Callable[[Exception], None],
    ) -> bool:
        if self.task and not self.task.done():
            return False
        self.task = asyncio.create_task(
            self._run(load_lifecycle, key_configured, refresh, report_error)
        )
        return True

    async def stop(self) -> None:
        task, self.task = self.task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run(
        self,
        load_lifecycle: Callable[[], dict[str, Any]],
        key_configured: Callable[[], bool],
        refresh: Callable[[], Awaitable[Any]],
        report_error: Callable[[Exception], None],
    ) -> None:
        while True:
            try:
                lifecycle = load_lifecycle()
                refreshed_at = lifecycle.get("refreshedAt")
                last = datetime.fromisoformat(str(refreshed_at)) if refreshed_at else None
                due = last is None or (
                    datetime.now(timezone.utc) - last.astimezone(timezone.utc)
                ).total_seconds() >= DAILY_REFRESH_SECONDS
                if due and key_configured():
                    await refresh()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                report_error(exc)
            await asyncio.sleep(60 * 60)


def _positive_number(value: Any) -> float | None:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def live_image_output_rate(model: dict[str, Any]) -> tuple[str, float] | None:
    """Return an explicit live image rate without inventing a fallback price."""

    pricing = model.get("pricing")
    if not isinstance(pricing, dict):
        return None
    for key in ("image_output", "image_token"):
        amount = _positive_number(pricing.get(key))
        if amount is not None:
            return ("token_estimate", amount)
    for key in ("image", "output_image"):
        amount = _positive_number(pricing.get(key))
        if amount is not None:
            return ("image", amount)
    return None


def live_image_price_specs(models: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for model in models:
        model_id = str(model.get("id") or "").strip()
        rate = live_image_output_rate(model)
        if not model_id or rate is None:
            continue
        pricing_type, usd = rate
        specs.append({
            "id": model_id,
            "name": str(model.get("name") or model_id),
            "provider": str(model.get("providerName") or model_id.split("/", 1)[0]),
            "pricing_type": pricing_type,
            "usd": usd,
            "min_tokens": 1,
            "source": "openrouter_live_catalog",
        })
    return specs


def fallback_image_capabilities(price_models: Iterable[Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": model.id,
            "name": model.name,
            "description": "Встроенный резервный каталог. Возможности endpoint будут уточнены в фоне.",
            "inputModalities": ["image", "text"],
            "outputModalities": ["image"],
            "parameters": [],
            "parameterDescriptors": {},
            "maxInputReferences": 1,
            "supportsStreaming": False,
            "modes": ["image_to_image", "paint", "text_to_image"],
            "features": {
                "seed": False,
                "quality": False,
                "aspectRatio": True,
                "resolution": True,
                "transparentBackground": False,
                "multipleOutputs": False,
            },
            "endpointVerified": False,
            "catalogSource": "fallback",
        }
        for model in price_models
    ]


def lifecycle_metadata(
    runtime_state: dict[str, Any],
    persisted: dict[str, Any],
) -> dict[str, Any] | None:
    current = runtime_state.get("lifecycle")
    if isinstance(current, dict):
        return current
    if not persisted:
        return None
    return {
        "refreshedAt": persisted.get("refreshedAt"),
        "refreshIntervalSeconds": persisted.get("refreshIntervalSeconds"),
        "changes": persisted.get("changes"),
    }


def key_status_snapshot(
    cached: Any,
    *,
    configured: bool,
    source: str,
) -> dict[str, Any]:
    if isinstance(cached, dict):
        return dict(cached)
    return {
        "configured": configured,
        "source": source,
        "ok": False,
        "pending": configured,
        "error": None if configured else "OPENROUTER_API_KEY не задан",
    }


def catalog_snapshot(
    image_cache: dict[str, Any],
    video_cache: dict[str, Any],
    state: dict[str, Any],
    fallback_models: list[dict[str, Any]],
    persisted_lifecycle: dict[str, Any],
    *,
    monotonic_now: float,
) -> dict[str, Any]:
    cached_images = image_cache.get("models")
    cached_videos = video_cache.get("models")
    images = list(cached_images) if isinstance(cached_images, list) and cached_images else fallback_models
    videos = list(cached_videos) if isinstance(cached_videos, list) else []
    image_ts = float(image_cache.get("ts") or 0)
    return {
        "models": images,
        "videoModels": videos,
        "meta": {
            **state,
            "source": "live-cache" if cached_images else "fallback",
            "modelCount": len(images),
            "videoModelCount": len(videos),
            "cacheAgeSeconds": int(max(0.0, monotonic_now - image_ts)) if image_ts else None,
            "lifecycle": lifecycle_metadata(state, persisted_lifecycle),
        },
    }


def catalog_refresh_needed(
    snapshot: dict[str, Any],
    *,
    has_cached_images: bool,
    key_pending: bool,
    ttl_seconds: int = DAILY_REFRESH_SECONDS,
) -> bool:
    meta = snapshot.get("meta") if isinstance(snapshot, dict) else {}
    age = meta.get("cacheAgeSeconds") if isinstance(meta, dict) else None
    return (
        not has_cached_images
        or age is None
        or int(age) >= ttl_seconds
        or key_pending
    )


def _pricing_signature(model: dict[str, Any], kind: str) -> tuple[tuple[str, float], ...]:
    source = model.get("pricingSkus") if kind == "video" else model.get("pricing")
    if not isinstance(source, dict):
        return ()
    values: list[tuple[str, float]] = []
    for key, value in source.items():
        amount = _positive_number(value)
        if amount is not None:
            values.append((str(key), amount))
    return tuple(sorted(values))


def _catalog_rows(models: Iterable[dict[str, Any]], kind: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for model in models:
        model_id = str(model.get("id") or "").strip()
        if not model_id:
            continue
        pricing = dict(_pricing_signature(model, kind))
        rows[model_id] = {
            "id": model_id,
            "name": str(model.get("name") or model_id),
            "pricing": pricing,
            "priced": bool(pricing),
            "modes": sorted(str(value) for value in model.get("modes") or []),
        }
    return rows


def build_catalog_lifecycle(
    image_models: Iterable[dict[str, Any]],
    video_models: Iterable[dict[str, Any]],
    previous: dict[str, Any] | None = None,
    *,
    refreshed_at: str | None = None,
) -> dict[str, Any]:
    """Create the persisted daily snapshot and a deterministic change report."""

    refreshed_at = refreshed_at or datetime.now(timezone.utc).isoformat()
    current = {
        "images": _catalog_rows(image_models, "image"),
        "videos": _catalog_rows(video_models, "video"),
    }
    previous_catalog = previous.get("catalog") if isinstance(previous, dict) else {}
    if not isinstance(previous_catalog, dict):
        previous_catalog = {}
    changes: dict[str, dict[str, list[str]]] = {}
    for kind in ("images", "videos"):
        before = previous_catalog.get(kind) if isinstance(previous_catalog.get(kind), dict) else {}
        after = current[kind]
        before_ids = set(before)
        after_ids = set(after)
        changes[kind] = {
            "added": sorted(after_ids - before_ids),
            "removed": sorted(before_ids - after_ids),
            "priceChanged": sorted(
                model_id
                for model_id in before_ids & after_ids
                if before[model_id].get("pricing") != after[model_id].get("pricing")
            ),
            "unpriced": sorted(model_id for model_id, row in after.items() if not row["priced"]),
        }
    return {
        "refreshedAt": refreshed_at,
        "refreshIntervalSeconds": DAILY_REFRESH_SECONDS,
        "catalog": current,
        "changes": changes,
    }
