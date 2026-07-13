from __future__ import annotations

from types import SimpleNamespace

from app.services.generation_results import (
    build_generation_image_record,
    complete_generation_job,
    fail_generation_job,
)


def request(*, prompt: str = "рисунок", provider: str = "comfyui") -> SimpleNamespace:
    return SimpleNamespace(
        mode="text_to_image",
        provider=provider,
        prompt=prompt,
        seed=42,
        width=704,
        height=960,
        modelProfile="local_flux_klein",
        loras=[SimpleNamespace(id="detail.safetensors"), SimpleNamespace(id="style.safetensors")],
    )


def test_comfyui_record_preserves_exact_worker_contract() -> None:
    record = build_generation_image_record(
        image_id="img_1",
        user_id="user_1",
        image_url="/api/media/a.png",
        thumbnail_url="/api/media/a.webp",
        request=request(),
        job={"tokenCost": 3, "openrouterBilling": {"ignored": True}},
        created_at="2026-07-14T00:00:00+00:00",
        generation_time_ms=1234,
        comfyui_prompt_id="prompt_1",
        comfyui_history={"prompt_1": {"status": "success"}},
    )

    assert record == {
        "id": "img_1",
        "userId": "user_1",
        "url": "/api/media/a.png",
        "thumbnailUrl": "/api/media/a.webp",
        "mode": "text_to_image",
        "provider": "comfyui",
        "promptOriginal": "рисунок",
        "promptTranslated": "",
        "seed": 42,
        "width": 704,
        "height": 960,
        "modelProfile": "local_flux_klein",
        "loras": ["detail.safetensors", "style.safetensors"],
        "preset": None,
        "tokenCost": 3,
        "generationTimeMs": 1234,
        "isFavorite": False,
        "createdAt": "2026-07-14T00:00:00+00:00",
        "comfyuiPromptId": "prompt_1",
        "comfyuiHistory": {"prompt_1": {"status": "success"}},
        "openrouterModel": None,
        "openrouterResponseId": None,
        "openrouterUsage": None,
        "openrouterCostUsd": None,
        "openrouterBilling": None,
        "openrouterRequest": None,
    }


def test_openrouter_record_uses_provider_dimensions_and_metadata() -> None:
    result = SimpleNamespace(
        width=1024,
        height=1024,
        model="provider/model",
        response_id="response_1",
        usage={"images": 1},
        cost_usd=0.014,
    )
    record = build_generation_image_record(
        image_id="img_2",
        user_id="user_2",
        image_url="/api/media/b.png",
        thumbnail_url="/api/media/b.webp",
        request=request(prompt="ascii prompt", provider="openrouter"),
        job={
            "tokenCost": 7,
            "openrouterBilling": {"actualTokens": 7},
            "openrouterRequest": {"model": "provider/model"},
        },
        created_at="2026-07-14T00:01:00+00:00",
        generation_time_ms=57,
        openrouter_result=result,
    )

    assert record["promptTranslated"] == "ascii prompt"
    assert (record["width"], record["height"]) == (1024, 1024)
    assert record["openrouterModel"] == "provider/model"
    assert record["openrouterResponseId"] == "response_1"
    assert record["openrouterUsage"] == {"images": 1}
    assert record["openrouterCostUsd"] == 0.014
    assert record["openrouterBilling"] == {"actualTokens": 7}
    assert record["openrouterRequest"] == {"model": "provider/model"}


def test_completed_job_state_preserves_unrelated_fields_and_exact_result_contract() -> None:
    job = {"id": "job_1", "tokenCost": 3, "error": "stale"}
    record = {"url": "/api/media/a.png", "width": 704, "height": 960}

    returned = complete_generation_job(
        job,
        record=record,
        result_image_id="img_1",
        gallery_save_status="saved",
        gallery_quota={"used": 1, "limit": 20},
        completed_at="2026-07-14T00:00:00+00:00",
    )

    assert returned is job
    assert job == {
        "id": "job_1",
        "tokenCost": 3,
        "error": "stale",
        "status": "completed",
        "progress": 100,
        "message": "Готово",
        "resultImageId": "img_1",
        "resultUrl": "/api/media/a.png",
        "width": 704,
        "height": 960,
        "gallerySaveStatus": "saved",
        "galleryQuota": {"used": 1, "limit": 20},
        "completedAt": "2026-07-14T00:00:00+00:00",
    }


def test_failed_job_state_preserves_unrelated_fields_and_exact_error_contract() -> None:
    job = {"id": "job_2", "tokenCost": 4}

    returned = fail_generation_job(
        job,
        error=RuntimeError("provider unavailable"),
        completed_at="2026-07-14T00:02:00+00:00",
    )

    assert returned is job
    assert job == {
        "id": "job_2",
        "tokenCost": 4,
        "status": "failed",
        "progress": 100,
        "message": "Генерация не выполнена.",
        "error": "provider unavailable",
        "completedAt": "2026-07-14T00:02:00+00:00",
    }
