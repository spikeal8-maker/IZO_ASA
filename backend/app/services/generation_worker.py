"""Single generation-job orchestration through injected runtime callbacks."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, Protocol

from . import generation_results
from ..generation_errors import GenerationClaimLost


class ComfyUIWorkerResult(Protocol):
    prompt_id: str
    image_path: Any
    thumbnail_path: Any
    history: Any


class OpenRouterWorkerResult(generation_results.OpenRouterGenerationResult, Protocol):
    image_path: Any
    thumbnail_path: Any


@dataclass(frozen=True)
class OpenRouterSettlement:
    billing: dict[str, Any]
    actual_tokens: int
    token_adjustment: dict[str, Any]


@dataclass(frozen=True)
class GenerationWorkerRuntime:
    comfyui_mock_fallback: bool
    persist_job: Callable[[dict[str, Any], Any], None]
    refund_tokens: Callable[[str, str], bool]
    send_to_comfyui: Callable[[Any, dict[str, Any]], Awaitable[ComfyUIWorkerResult | None]]
    send_to_openrouter: Callable[[Any, dict[str, Any]], Awaitable[OpenRouterWorkerResult]]
    settle_openrouter: Callable[[str, dict[str, Any], OpenRouterWorkerResult], OpenRouterSettlement]
    mock_image: Callable[[Any, str], tuple[Any, Any]]
    gallery_quota: Callable[[str], dict[str, Any]]
    evict_gallery: Callable[[str, dict[str, Any], str], int]
    public_url: Callable[[Any, str], str]
    new_image_id: Callable[[], str]
    now_iso: Callable[[], str]
    perf_counter: Callable[[], float]
    sleep: Callable[[float], Awaitable[None]]
    save_image: Callable[[dict[str, Any], str, str, Any, str], Awaitable[None]]
    register_transient_image: Callable[[dict[str, Any]], None]
    claim_job: Callable[..., Any] = lambda _job_id, _job: nullcontext(True)
    finalization: Callable[[], Any] = nullcontext
    refresh_job: Callable[..., None] = lambda _job_id, _job: None
    after_completion: Callable[[str], Awaitable[None]] | None = None


async def process_generation_job(
    job_id: str,
    job: dict[str, Any],
    request: generation_results.GenerationRequest,
    runtime: GenerationWorkerRuntime,
    *,
    started_at: float,
) -> None:
    completed_user = None
    try:
        with runtime.claim_job(job_id, job) as acquired:
            if not acquired:
                runtime.refresh_job(job_id, job)
                return
            completed_user = await _process_claimed_job(
                job_id, job, request, runtime, started_at=started_at,
            )
    except GenerationClaimLost:
        runtime.refresh_job(job_id, job)
    if completed_user is not None and runtime.after_completion is not None:
        await runtime.after_completion(completed_user)


async def _process_claimed_job(
    job_id: str,
    job: dict[str, Any],
    request: generation_results.GenerationRequest,
    runtime: GenerationWorkerRuntime,
    *,
    started_at: float,
) -> str | None:
    before_finalization = None
    try:
        if job.get("status") == "cancelled":
            with runtime.finalization():
                runtime.refund_tokens(job_id, "cancelled_before_start")
                runtime.persist_job(job, request)
            return

        if not job.get("startedAt"):
            job["startedAt"] = runtime.now_iso()
        job.update(status="uploading", progress=12, message="Загружаем изображения")
        runtime.persist_job(job, request)
        await runtime.sleep(0.5)

        prompt_id = None
        image_path = None
        thumbnail_path = None
        comfyui_history = None
        openrouter_result: OpenRouterWorkerResult | None = None
        if request.provider == "comfyui":
            job.update(status="sent_to_comfyui", progress=24, message="Отправляем в ComfyUI")
            runtime.persist_job(job, request)
            result = await runtime.send_to_comfyui(request, job)
            if result:
                prompt_id = result.prompt_id
                image_path = result.image_path
                thumbnail_path = result.thumbnail_path
                comfyui_history = result.history
        elif request.provider == "openrouter":
            openrouter_result = await runtime.send_to_openrouter(request, job)
            image_path = openrouter_result.image_path
            thumbnail_path = openrouter_result.thumbnail_path

        if not image_path:
            if request.provider == "comfyui" and not runtime.comfyui_mock_fallback:
                raise RuntimeError("ComfyUI не вернул изображение, mock fallback отключён.")
            if request.provider == "openrouter":
                raise RuntimeError("OpenRouter не вернул изображение.")
            await runtime.sleep(0.8)
            for progress in (38, 52, 67, 81, 94):
                if job["status"] == "cancelled":
                    break
                job.update(status="running", progress=progress, message="Генерация изображения")
                runtime.persist_job(job, request)
                await runtime.sleep(0.45)

        if job["status"] == "cancelled":
            with runtime.finalization():
                runtime.refund_tokens(job_id, "cancelled_during_generation")
                runtime.persist_job(job, request)
            return

        before_finalization = dict(job)
        with runtime.finalization():
            if openrouter_result is not None:
                settlement = runtime.settle_openrouter(job_id, job, openrouter_result)
                job.update(
                    openrouterModel=openrouter_result.model,
                    openrouterResponseId=openrouter_result.response_id,
                    openrouterUsage=openrouter_result.usage,
                    openrouterCostUsd=openrouter_result.cost_usd,
                    openrouterBilling=settlement.billing,
                    tokenCost=int(settlement.token_adjustment.get("settled") or settlement.actual_tokens),
                    tokenAdjustment=settlement.token_adjustment,
                )
            if not image_path or not thumbnail_path:
                image_path, thumbnail_path = runtime.mock_image(request, job_id)

            user_id = job.get("userId", "demo_user")
            gallery_quota = runtime.gallery_quota(user_id)
            image_id = runtime.new_image_id()
            created_at = runtime.now_iso()
            record = generation_results.build_generation_image_record(
                image_id=image_id,
                user_id=user_id,
                image_url=runtime.public_url(image_path, user_id),
                thumbnail_url=runtime.public_url(thumbnail_path, user_id),
                request=request,
                job=job,
                created_at=created_at,
                generation_time_ms=int((runtime.perf_counter() - started_at) * 1000),
                comfyui_prompt_id=prompt_id,
                comfyui_history=comfyui_history,
                openrouter_result=openrouter_result,
            )

            if gallery_quota["gallery_full"]:
                evicted_count = runtime.evict_gallery(user_id, gallery_quota, created_at)
                if evicted_count:
                    await runtime.save_image(record, job_id, user_id, request, created_at)
                    save_status = "saved"
                    result_image_id = image_id
                else:
                    runtime.register_transient_image(record)
                    save_status = "quota_full"
                    result_image_id = None
                gallery_quota = runtime.gallery_quota(user_id)
            else:
                await runtime.save_image(record, job_id, user_id, request, created_at)
                gallery_quota = runtime.gallery_quota(user_id)
                save_status = "saved"
                result_image_id = image_id

            generation_results.complete_generation_job(
                job,
                record=record,
                result_image_id=result_image_id,
                gallery_save_status=save_status,
                gallery_quota=gallery_quota,
                completed_at=created_at,
            )
            runtime.persist_job(job, request)
        return user_id
    except GenerationClaimLost:
        raise
    except Exception as exc:
        if before_finalization is not None:
            job.clear()
            job.update(before_finalization)
        with runtime.finalization():
            runtime.refund_tokens(job_id, "generation_failed")
            generation_results.fail_generation_job(
                job,
                error=exc,
                completed_at=runtime.now_iso(),
            )
            runtime.persist_job(job, request)
