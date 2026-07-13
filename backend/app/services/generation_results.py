"""Pure builders for generated image records and terminal job states."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol


class GenerationLora(Protocol):
    id: str


class GenerationRequest(Protocol):
    mode: str
    provider: str
    prompt: str
    seed: int
    width: int
    height: int
    modelProfile: str
    loras: Sequence[GenerationLora]


class OpenRouterGenerationResult(Protocol):
    width: int
    height: int
    model: str
    response_id: str | None
    usage: dict[str, Any]
    cost_usd: float | None


def build_generation_image_record(
    *,
    image_id: str,
    user_id: str,
    image_url: str,
    thumbnail_url: str,
    request: GenerationRequest,
    job: Mapping[str, Any],
    created_at: str,
    generation_time_ms: int,
    comfyui_prompt_id: str | None = None,
    comfyui_history: Any = None,
    openrouter_result: OpenRouterGenerationResult | None = None,
) -> dict[str, Any]:
    return {
        "id": image_id,
        "userId": user_id,
        "url": image_url,
        "thumbnailUrl": thumbnail_url,
        "mode": request.mode,
        "provider": request.provider,
        "promptOriginal": request.prompt,
        "promptTranslated": request.prompt if request.prompt.isascii() else "",
        "seed": request.seed,
        "width": openrouter_result.width if openrouter_result else request.width,
        "height": openrouter_result.height if openrouter_result else request.height,
        "modelProfile": request.modelProfile,
        "loras": [item.id for item in request.loras],
        "preset": None,
        "tokenCost": job.get("tokenCost"),
        "generationTimeMs": generation_time_ms,
        "isFavorite": False,
        "createdAt": created_at,
        "comfyuiPromptId": comfyui_prompt_id,
        "comfyuiHistory": comfyui_history,
        "openrouterModel": openrouter_result.model if openrouter_result else None,
        "openrouterResponseId": openrouter_result.response_id if openrouter_result else None,
        "openrouterUsage": openrouter_result.usage if openrouter_result else None,
        "openrouterCostUsd": openrouter_result.cost_usd if openrouter_result else None,
        "openrouterBilling": job.get("openrouterBilling") if openrouter_result else None,
        "openrouterRequest": job.get("openrouterRequest") if openrouter_result else None,
    }


def complete_generation_job(
    job: dict[str, Any],
    *,
    record: Mapping[str, Any],
    result_image_id: str | None,
    gallery_save_status: str,
    gallery_quota: Mapping[str, Any],
    completed_at: str,
) -> dict[str, Any]:
    job.update(
        status="completed",
        progress=100,
        message="Готово",
        resultImageId=result_image_id,
        resultUrl=record["url"],
        width=record["width"],
        height=record["height"],
        gallerySaveStatus=gallery_save_status,
        galleryQuota=gallery_quota,
        completedAt=completed_at,
    )
    return job


def fail_generation_job(
    job: dict[str, Any],
    *,
    error: BaseException | str,
    completed_at: str,
) -> dict[str, Any]:
    job.update(
        status="failed",
        progress=100,
        message="Генерация не выполнена.",
        error=str(error),
        completedAt=completed_at,
    )
    return job
