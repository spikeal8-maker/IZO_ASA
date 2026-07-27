"""Fallback pricing for video models whose catalog rate is not published yet."""

from __future__ import annotations

from dataclasses import dataclass
import re
from statistics import fmean
from typing import Any, Callable, Iterable


STARTING_USD_PER_SECOND = {
    "480p": 0.08,
    "720p": 0.10,
    "1024p": 0.16,
    "1080p": 0.18,
    "1k": 0.16,
    "2k": 0.28,
    "4k": 0.35,
}


def video_size(model: dict[str, Any], resolution: str, aspect_ratio: str) -> tuple[int, int] | None:
    ratio_parts = [int(value) for value in aspect_ratio.split(":") if value.isdigit()]
    target_ratio = ratio_parts[0] / ratio_parts[1] if len(ratio_parts) == 2 and ratio_parts[1] else None
    sizes: list[tuple[int, int]] = []
    for raw in model.get("supportedSizes") or []:
        match = re.fullmatch(r"(\d+)x(\d+)", str(raw).lower())
        if match:
            sizes.append((int(match.group(1)), int(match.group(2))))
    resolution_key = str(resolution or "").strip().lower()
    short = {"1k": 1024, "2k": 1440, "4k": 2160}.get(resolution_key) or int(re.sub(r"\D", "", resolution_key) or 720)
    if sizes:
        def score(size: tuple[int, int]) -> tuple[float, float]:
            resolution_error = abs(min(size) - short) / max(short, 1)
            aspect_error = abs(size[0] / size[1] - target_ratio) if target_ratio else 0.0
            return resolution_error, aspect_error
        return min(sizes, key=score)
    if target_ratio and target_ratio >= 1:
        return max(short, round(short * target_ratio)), short
    if target_ratio:
        return short, max(short, round(short / target_ratio))
    return None


def allowed_models(
    catalog: list[dict[str, Any]],
    config: dict[str, Any],
    mode: str,
    plan: str,
    is_admin: bool,
) -> list[dict[str, Any]]:
    enabled = set((config.get("enabled") or {}).get(mode) or [])
    tier = set((((config.get("access") or {}).get(mode) or {}).get(plan)) or [])
    allowed = enabled if is_admin else enabled.intersection(tier)
    return [
        model
        for model in catalog
        if model.get("id") in allowed and mode in (model.get("modes") or [])
    ]


@dataclass(frozen=True)
class VideoFallbackRate:
    usd_per_second: float
    source: str
    sample_count: int


@dataclass(frozen=True)
class VideoPricingRate:
    usd_rate: float
    unit: str
    source_key: str | None
    source: str
    fallback: bool
    sample_count: int


def actual_pricing_samples(
    rows: Iterable[Any],
    parse_json: Callable[[Any], Any],
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for row in rows:
        settings = parse_json(row["settings_json"]) or {}
        if not isinstance(settings, dict):
            continue
        billing = settings.get("openrouterBilling") if isinstance(settings.get("openrouterBilling"), dict) else {}
        actual_cost = billing.get("actualCostUsd")
        if not isinstance(actual_cost, (int, float)):
            actual_cost = settings.get("openrouterCostUsd")
        if not isinstance(actual_cost, (int, float)) or float(actual_cost) <= 0:
            continue
        samples.append({
            "modelId": settings.get("openrouterModel"),
            "mode": row["mode"],
            "duration": settings.get("duration"),
            "resolution": settings.get("resolution"),
            "aspectRatio": settings.get("aspectRatio"),
            "generateAudio": bool(settings.get("generateAudio")),
            "actualCostUsd": float(actual_cost),
        })
    return samples


def load_actual_pricing_samples(
    open_db: Callable[[], Any],
    parse_json: Callable[[Any], Any],
) -> list[dict[str, Any]]:
    with open_db() as conn:
        rows = conn.execute(
            "SELECT mode, settings_json FROM jobs "
            "WHERE provider='openrouter' AND status='completed' "
            "AND mode IN ('text_to_video','image_to_video','first_last_frame','reference_to_video') "
            "ORDER BY completed_at DESC LIMIT 500"
        ).fetchall()
    return actual_pricing_samples(rows, parse_json)


def _starting_rate(resolution: str, mode: str, generate_audio: bool) -> float:
    rate = STARTING_USD_PER_SECOND.get(str(resolution).lower(), 0.12)
    if mode == "first_last_frame":
        rate *= 1.08
    elif mode == "reference_to_video":
        rate *= 1.15
    if generate_audio:
        rate *= 1.25
    return rate


def _sample_rates(
    samples: Iterable[dict[str, Any]],
    *,
    model_id: str | None,
    mode: str,
    resolution: str,
    aspect_ratio: str,
    generate_audio: bool,
) -> list[float]:
    exact: list[float] = []
    compatible: list[float] = []
    for sample in samples:
        if model_id is not None and str(sample.get("modelId") or "") != model_id:
            continue
        if str(sample.get("mode") or "") != mode:
            continue
        if str(sample.get("resolution") or "").lower() != resolution.lower():
            continue
        if bool(sample.get("generateAudio")) != generate_audio:
            continue
        try:
            duration = float(sample.get("duration") or 0)
            cost_usd = float(sample.get("actualCostUsd") or 0)
        except (TypeError, ValueError):
            continue
        if duration <= 0 or cost_usd <= 0:
            continue
        rate = cost_usd / duration
        compatible.append(rate)
        if str(sample.get("aspectRatio") or "") == aspect_ratio:
            exact.append(rate)
    return exact or compatible


def estimate_fallback_video_rate(
    *,
    model_id: str,
    mode: str,
    resolution: str,
    aspect_ratio: str,
    generate_audio: bool,
    samples: Iterable[dict[str, Any]],
) -> VideoFallbackRate:
    """Prefer actual model history, then comparable jobs, then a safe baseline."""

    sample_rows = list(samples)
    baseline = _starting_rate(resolution, mode, generate_audio)
    model_rates = _sample_rates(
        sample_rows,
        model_id=model_id,
        mode=mode,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        generate_audio=generate_audio,
    )
    if model_rates:
        reserve = 1.15 if len(model_rates) >= 3 else 1.25
        floor = baseline * (0.25 if len(model_rates) >= 3 else 0.75)
        return VideoFallbackRate(
            usd_per_second=round(max(fmean(model_rates) * reserve, floor), 8),
            source="model_history",
            sample_count=len(model_rates),
        )

    cohort_rates = _sample_rates(
        sample_rows,
        model_id=None,
        mode=mode,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        generate_audio=generate_audio,
    )
    if cohort_rates:
        return VideoFallbackRate(
            usd_per_second=round(max(fmean(cohort_rates) * 1.25, baseline), 8),
            source="cohort_history",
            sample_count=len(cohort_rates),
        )

    return VideoFallbackRate(
        usd_per_second=round(baseline, 8),
        source="startup_baseline",
        sample_count=0,
    )


def resolve_video_rate(
    model: dict[str, Any],
    *,
    model_id: str,
    mode: str,
    resolution: str,
    aspect_ratio: str,
    generate_audio: bool,
    samples: Iterable[dict[str, Any]],
) -> VideoPricingRate:
    pricing = model.get("pricingSkus") if isinstance(model.get("pricingSkus"), dict) else {}
    resolution_key = resolution.lower()
    prefix = "text_to_video_duration_seconds" if mode == "text_to_video" else "image_to_video_duration_seconds"
    preferred = [
        f"{prefix}_{resolution_key}",
        f"duration_seconds_{'with' if generate_audio else 'without'}_audio_{resolution_key}",
        f"duration_seconds_{resolution_key}",
        prefix,
        f"duration_seconds_{'with' if generate_audio else 'without'}_audio",
        "duration_seconds",
    ]
    for key in preferred:
        if isinstance(pricing.get(key), (int, float)):
            return VideoPricingRate(float(pricing[key]), "second", key, "catalog", False, 0)
    for key in (f"cents_per_video_output_second_{resolution_key}", "cents_per_video_output_second"):
        if isinstance(pricing.get(key), (int, float)):
            return VideoPricingRate(float(pricing[key]) / 100, "second", key, "catalog", False, 0)
    token_key = "video_tokens" if generate_audio or not isinstance(pricing.get("video_tokens_without_audio"), (int, float)) else "video_tokens_without_audio"
    if isinstance(pricing.get(token_key), (int, float)):
        return VideoPricingRate(float(pricing[token_key]), "video_token", token_key, "catalog", False, 0)
    generic = next(((str(key), float(value)) for key, value in pricing.items() if isinstance(value, (int, float)) and "duration" in str(key)), None)
    if generic:
        return VideoPricingRate(generic[1], "second", generic[0], "catalog", False, 0)
    fallback = estimate_fallback_video_rate(
        model_id=model_id,
        mode=mode,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        generate_audio=generate_audio,
        samples=samples,
    )
    return VideoPricingRate(
        fallback.usd_per_second,
        "second",
        f"fallback:{fallback.source}:{fallback.sample_count}",
        fallback.source,
        True,
        fallback.sample_count,
    )
