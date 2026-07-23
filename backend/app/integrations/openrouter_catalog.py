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


def reviewed_image_price_specs() -> list[dict[str, Any]]:
    """Operator-reviewed prices; these always win over live discovery data."""

    rows = [
        ("black-forest-labs/flux.2-klein-4b", "FLUX.2 Klein 4B", "BFL", "mp", .014, 1, "reviewed"),
        ("black-forest-labs/flux.2-pro", "FLUX.2 Pro", "BFL", "mp", .03, 2, "reviewed"),
        ("black-forest-labs/flux.2-max", "FLUX.2 Max", "BFL", "mp", .07, 3, "reviewed"),
        ("black-forest-labs/flux.2-flex", "FLUX.2 Flex", "BFL", "mp", .12, 4, "reviewed"),
        ("openai/gpt-image-1-mini", "GPT Image 1 Mini", "OpenAI", "token_estimate", .000008, 1, "reviewed"),
        ("openai/gpt-5-image-mini", "GPT-5 Image Mini", "OpenAI", "token_estimate", .000008, 1, "reviewed"),
        ("openai/gpt-image-1", "GPT Image 1", "OpenAI", "token_estimate", .00004, 2, "reviewed"),
        ("openai/gpt-5-image", "GPT-5 Image", "OpenAI", "token_estimate", .00004, 2, "reviewed"),
        ("openai/gpt-image-2", "GPT Image 2", "OpenAI", "token_estimate", .00003, 1, "reviewed"),
        ("openai/gpt-5.4-image-2", "GPT-5.4 Image 2", "OpenAI", "token_estimate", .00003, 1, "reviewed"),
        ("google/gemini-3.1-flash-lite-image", "Nano Banana 2 Lite", "Google Vertex", "token_estimate", .00003, 1, "reviewed"),
        ("google/gemini-3.1-flash-image", "Nano Banana 2", "Google Vertex", "token_estimate", .00006, 2, "reviewed"),
        ("google/gemini-3.1-flash-image-preview", "Nano Banana 2 Preview", "Google Vertex", "token_estimate", .00006, 2, "market_estimate_2026-07-10"),
        ("google/gemini-3-pro-image", "Nano Banana Pro", "Google Vertex", "token_estimate", .00012, 4, "reviewed"),
        ("google/gemini-3-pro-image-preview", "Nano Banana Pro Preview", "Google Vertex", "token_estimate", .00012, 4, "market_estimate_2026-07-10"),
        ("google/gemini-2.5-flash-image", "Gemini 2.5 Flash Image", "Google", "token_estimate", .00006, 2, "market_estimate_2026-07-10"),
        ("google/gemini-2.5-flash-image-preview", "Gemini 2.5 Flash Image Preview", "Google", "token_estimate", .00006, 2, "market_estimate_2026-07-10"),
        ("microsoft/mai-image-2.5", "MAI-Image-2.5", "Microsoft", "token_estimate", .00006, 2, "market_estimate_2026-07-10"),
        ("x-ai/grok-imagine-image-quality", "Grok Imagine Image Quality", "xAI", "image", .07, 3, "market_estimate_2026-07-10"),
        ("recraft/recraft-v4.1", "Recraft V4.1", "Recraft", "image", .035, 1, "reviewed"),
        ("recraft/recraft-v4.1-utility", "Recraft V4.1 Utility", "Recraft", "image", .035, 1, "reviewed"),
        ("recraft/recraft-v4.1-pro", "Recraft V4.1 Pro", "Recraft", "image", .21, 6, "reviewed"),
        ("recraft/recraft-v4.1-utility-pro", "Recraft V4.1 Utility Pro", "Recraft", "image", .21, 6, "reviewed"),
        ("recraft/recraft-v4.1-vector", "Recraft V4.1 Vector", "Recraft", "image", .08, 3, "reviewed"),
        ("recraft/recraft-v4.1-pro-vector", "Recraft V4.1 Pro Vector", "Recraft", "image", .30, 8, "reviewed"),
        ("recraft/recraft-v4", "Recraft V4", "Recraft", "image", .04, 1, "reviewed"),
        ("recraft/recraft-v4-pro", "Recraft V4 Pro", "Recraft", "image", .25, 7, "reviewed"),
        ("recraft/recraft-v4-vector", "Recraft V4 Vector", "Recraft", "image", .08, 3, "reviewed"),
        ("recraft/recraft-v4-pro-vector", "Recraft V4 Pro Vector", "Recraft", "image", .30, 8, "reviewed"),
        ("recraft/recraft-v3", "Recraft V3", "Recraft", "image", .04, 1, "reviewed"),
        ("sourceful/riverflow-v2-fast", "Riverflow V2 Fast", "Sourceful", "image", .04, 1, "market_estimate_2026-07-10"),
        ("sourceful/riverflow-v2-pro", "Riverflow V2 Pro", "Sourceful", "image", .13, 3, "market_estimate_2026-07-10"),
        ("sourceful/riverflow-v2.5-fast", "Riverflow V2.5 Fast", "Sourceful", "image", .019, 1, "reviewed"),
        ("sourceful/riverflow-v2.5-pro", "Riverflow V2.5 Pro", "Sourceful", "image", .13, 3, "reviewed"),
        ("sourceful/riverflow-v2-fast-preview", "Riverflow V2 Fast Preview", "Sourceful", "image", .04, 1, "market_estimate_2026-07-10"),
        ("sourceful/riverflow-v2-standard-preview", "Riverflow V2 Standard Preview", "Sourceful", "image", .08, 2, "market_estimate_2026-07-10"),
        ("sourceful/riverflow-v2-max-preview", "Riverflow V2 Max Preview", "Sourceful", "image", .13, 3, "market_estimate_2026-07-10"),
        ("bytedance-seed/seedream-4.5", "Seedream 4.5", "ByteDance Seed", "image", .04, 1, "reviewed"),
        ("openrouter/auto", "Auto Router", "OpenRouter", "image", .15, 4, "market_estimate_2026-07-10"),
    ]
    return [
        {"id": row[0], "name": row[1], "provider": row[2], "pricing_type": row[3],
         "usd": row[4], "min_tokens": row[5], "source": row[6]}
        for row in rows
    ]


def normalize_economy_settings(
    raw: dict[str, Any],
    *,
    default_margin_percent: float,
    default_token_rub: float,
    usd_fee_rate: float,
) -> dict[str, float]:
    try:
        margin = float(raw.get("minMarginPercent", default_margin_percent))
    except (TypeError, ValueError):
        margin = default_margin_percent
    try:
        token_rub = float(raw.get("tokenRub", default_token_rub))
    except (TypeError, ValueError):
        token_rub = default_token_rub
    return {
        "minMarginPercent": max(0.0, min(95.0, margin)),
        "tokenRub": max(0.01, min(100000.0, token_rub)),
        "usdFeePercent": usd_fee_rate * 100,
    }


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
