from __future__ import annotations

from dataclasses import dataclass
from typing import Any


LOCAL_LTX_MODEL_PREFIX = "local/ltx-2.3"


@dataclass(frozen=True)
class LtxProfile:
    model_id: str
    name: str
    description: str
    quantization: str
    width: int
    height: int
    steps: int
    tokens_by_duration: dict[int, int]

    @property
    def durations(self) -> list[int]:
        return sorted(self.tokens_by_duration)


_PROFILES = (
    LtxProfile(
        model_id=f"{LOCAL_LTX_MODEL_PREFIX}-fast-q3",
        name="LTX 2.3 Локально — быстро",
        description="Локальная генерация на видеокарте. Короткие ролики без звука, очередь по одному заданию.",
        quantization="Q3_K_M",
        width=832,
        height=480,
        steps=8,
        tokens_by_duration={2: 1, 4: 2},
    ),
    LtxProfile(
        model_id=f"{LOCAL_LTX_MODEL_PREFIX}-standard-q4",
        name="LTX 2.3 Локально — стандарт",
        description="Локальная генерация повышенного качества. Короткие ролики без звука, очередь по одному заданию.",
        quantization="Q4_K_M",
        width=832,
        height=480,
        steps=12,
        tokens_by_duration={2: 2, 4: 4},
    ),
)


def resolve_local_ltx_profile(model_id: str) -> LtxProfile | None:
    return next((profile for profile in _PROFILES if profile.model_id == model_id), None)


def local_ltx_catalog(*, enabled: bool) -> list[dict[str, Any]]:
    if not enabled:
        return []
    return [
        {
            "id": profile.model_id,
            "name": profile.name,
            "description": profile.description,
            "provider": "local_ltx",
            "modes": ["text_to_video"],
            "supportedResolutions": ["480p"],
            "supportedAspectRatios": ["16:9"],
            "supportedSizes": [f"{profile.width}x{profile.height}"],
            "supportedDurations": profile.durations,
            "supportedFrameImages": [],
            "generateAudio": False,
            "localProfile": {
                "quantization": profile.quantization,
                "steps": profile.steps,
                "concurrency": 1,
            },
            "publicPricing": {
                "fromTokens": min(profile.tokens_by_duration.values()),
                "examples": [
                    {
                        "duration": duration,
                        "resolution": "480p",
                        "aspectRatio": "16:9",
                        "tokens": tokens,
                        "pricingSource": "local_profile",
                    }
                    for duration, tokens in sorted(profile.tokens_by_duration.items())
                ],
                "estimated": False,
            },
        }
        for profile in _PROFILES
    ]


def catalog_for_mode(mode: str, *, enabled: bool) -> list[dict[str, Any]]:
    return local_ltx_catalog(enabled=enabled) if mode == "text_to_video" else []


def resolve_catalog_model(
    model_id: str,
    mode: str,
    *,
    enabled: bool,
) -> tuple[dict[str, Any], LtxProfile] | None:
    profile = resolve_local_ltx_profile(model_id)
    if profile is None:
        return None
    model = next(
        (item for item in catalog_for_mode(mode, enabled=enabled) if item["id"] == model_id),
        None,
    )
    return (model, profile) if model is not None else None


def estimate_local_ltx_billing(profile: LtxProfile, *, duration: int) -> dict[str, Any]:
    tokens = profile.tokens_by_duration.get(duration)
    if tokens is None:
        raise ValueError("unsupported duration")
    return {
        "billingStatus": "quoted",
        "modelId": profile.model_id,
        "pricingKey": "local_profile",
        "pricingSource": "local_profile",
        "pricingFallback": False,
        "pricingSampleCount": 0,
        "chargedTokens": tokens,
        "estimatedCostUsd": 0.0,
        "estimatedCostRub": 0.0,
        "profitRub": None,
        "size": f"{profile.width}x{profile.height}",
    }
