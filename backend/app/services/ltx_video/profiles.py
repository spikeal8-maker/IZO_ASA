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
        name="LTX 2.3 — локально",
        description="Локальная генерация видео на выделенной RTX 4070. Короткие ролики без звука, очередь по одному заданию.",
        quantization="Q3_K_M",
        width=832,
        height=480,
        steps=8,
        tokens_by_duration={2: 1, 4: 2},
    ),
    # Kept as an administrator-selectable technical quality profile.  It is
    # deliberately not exposed as a second user-facing model.
    LtxProfile(
        model_id=f"{LOCAL_LTX_MODEL_PREFIX}-standard-q4",
        name="LTX 2.3 — Q4",
        description="Технический профиль повышенного качества.",
        quantization="Q4_K_M",
        width=832,
        height=480,
        steps=12,
        tokens_by_duration={2: 2, 4: 4},
    ),
)


LTX_480P_SIZES = {
    "16:9": (832, 480),
    "9:16": (480, 832),
    "1:1": (640, 640),
}


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
            "supportedAspectRatios": list(LTX_480P_SIZES),
            "supportedSizes": [
                f"{width}x{height}" for width, height in LTX_480P_SIZES.values()
            ],
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
                        "aspectRatio": aspect_ratio,
                        "tokens": tokens,
                        "pricingSource": "local_profile",
                    }
                    for duration, tokens in sorted(profile.tokens_by_duration.items())
                    for aspect_ratio in LTX_480P_SIZES
                ],
                "estimated": False,
            },
        }
        for profile in _PROFILES[:1]
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
