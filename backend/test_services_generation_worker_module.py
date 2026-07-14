from __future__ import annotations

import asyncio
import copy
import inspect
from types import SimpleNamespace
from typing import Any

import app.services.generation_worker as generation_worker_module
from app.services.generation_worker import (
    GenerationWorkerRuntime,
    OpenRouterSettlement,
    process_generation_job,
)


def request(*, provider: str = "comfyui", prompt: str = "worker test") -> SimpleNamespace:
    return SimpleNamespace(
        mode="text_to_image",
        provider=provider,
        prompt=prompt,
        seed=42,
        width=704,
        height=960,
        modelProfile="local_flux_klein",
        loras=[],
    )


class Harness:
    def __init__(self) -> None:
        self.events: list[tuple[Any, ...]] = []
        self.persisted: list[dict[str, Any]] = []
        self.refunds: list[tuple[str, str]] = []
        self.saved: list[dict[str, Any]] = []
        self.transient: list[dict[str, Any]] = []
        self.comfy_result: Any = SimpleNamespace(
            prompt_id="prompt_1",
            image_path="generated.png",
            thumbnail_path="generated.webp",
            history={"outputs": {}},
        )
        self.openrouter_result: Any = SimpleNamespace(
            image_path="openrouter.png",
            thumbnail_path="openrouter.webp",
            response_id="response_1",
            model="provider/model",
            usage={"images": 1},
            cost_usd=0.014,
            width=1024,
            height=1024,
        )
        self.provider_error: Exception | None = None
        self.quota_values = [
            {"gallery_full": False, "gallery_used": 0, "gallery_slots": 20},
            {"gallery_full": False, "gallery_used": 1, "gallery_slots": 20},
        ]
        self.evicted_count = 0
        self.mock_fallback = False
        self.cancel_job: dict[str, Any] | None = None
        self.cancel_on_sleep: float | None = None

    def persist_job(self, job: dict[str, Any], _request: Any) -> None:
        self.events.append(("persist", job.get("status"), job.get("progress")))
        self.persisted.append(copy.deepcopy(job))

    def refund_tokens(self, job_id: str, reason: str) -> bool:
        self.events.append(("refund", reason))
        self.refunds.append((job_id, reason))
        return True

    async def send_to_comfyui(self, _request: Any, _job: dict[str, Any]) -> Any:
        self.events.append(("comfyui",))
        if self.provider_error:
            raise self.provider_error
        return self.comfy_result

    async def send_to_openrouter(self, _request: Any, _job: dict[str, Any]) -> Any:
        self.events.append(("openrouter",))
        if self.provider_error:
            raise self.provider_error
        return self.openrouter_result

    def settle_openrouter(self, job_id: str, job: dict[str, Any], result: Any) -> OpenRouterSettlement:
        self.events.append(("settle", job_id, result.cost_usd))
        return OpenRouterSettlement(
            billing={"actualTokens": 3, "chargedTokens": 7},
            actual_tokens=3,
            token_adjustment={"settled": 2, "refund": 5, "adjusted": True},
        )

    def mock_image(self, _request: Any, job_id: str) -> tuple[str, str]:
        self.events.append(("mock", job_id))
        return "mock.png", "mock.webp"

    def gallery_quota(self, user_id: str) -> dict[str, Any]:
        self.events.append(("quota", user_id))
        if len(self.quota_values) > 1:
            return copy.deepcopy(self.quota_values.pop(0))
        return copy.deepcopy(self.quota_values[0])

    def evict_gallery(self, user_id: str, quota: dict[str, Any], created_at: str) -> int:
        self.events.append(("evict", user_id, quota["gallery_used"], created_at))
        return self.evicted_count

    def public_url(self, path: Any, user_id: str) -> str:
        return f"/api/media/{user_id}/{path}"

    async def save_image(
        self,
        record: dict[str, Any],
        job_id: str,
        user_id: str,
        _request: Any,
        created_at: str,
    ) -> None:
        self.events.append(("save", record["id"], job_id, user_id, created_at))
        self.saved.append(copy.deepcopy(record))

    def register_transient_image(self, record: dict[str, Any]) -> None:
        self.events.append(("transient", record["id"]))
        self.transient.append(copy.deepcopy(record))

    async def sleep(self, seconds: float) -> None:
        self.events.append(("sleep", seconds))
        if self.cancel_on_sleep == seconds and self.cancel_job is not None:
            self.cancel_job["status"] = "cancelled"

    def runtime(self) -> GenerationWorkerRuntime:
        return GenerationWorkerRuntime(
            comfyui_mock_fallback=self.mock_fallback,
            persist_job=self.persist_job,
            refund_tokens=self.refund_tokens,
            send_to_comfyui=self.send_to_comfyui,
            send_to_openrouter=self.send_to_openrouter,
            settle_openrouter=self.settle_openrouter,
            mock_image=self.mock_image,
            gallery_quota=self.gallery_quota,
            evict_gallery=self.evict_gallery,
            public_url=self.public_url,
            new_image_id=lambda: "img_worker_1",
            now_iso=lambda: "2026-07-14T00:00:00+00:00",
            perf_counter=lambda: 12.25,
            sleep=self.sleep,
            save_image=self.save_image,
            register_transient_image=self.register_transient_image,
        )


def run(job: dict[str, Any], payload: Any, harness: Harness) -> None:
    asyncio.run(
        process_generation_job(
            job["id"],
            job,
            payload,
            harness.runtime(),
            started_at=10.0,
        )
    )


def base_job(*, provider: str = "comfyui", status: str = "queued") -> dict[str, Any]:
    return {
        "id": "job_1",
        "userId": "user_1",
        "provider": provider,
        "status": status,
        "progress": 0,
        "tokenCost": 7,
    }


def test_worker_module_has_no_framework_database_or_storage_dependencies() -> None:
    source = inspect.getsource(generation_worker_module).lower()

    for forbidden in ("fastapi", "pydantic", "sqlite3", "httpx", "os.environ", "pathlib"):
        assert forbidden not in source


def test_cancelled_before_start_refunds_and_never_calls_provider() -> None:
    harness = Harness()
    job = base_job(status="cancelled")

    run(job, request(), harness)

    assert harness.refunds == [("job_1", "cancelled_before_start")]
    assert [item[0] for item in harness.events] == ["refund", "persist"]
    assert harness.persisted == [job]


def test_comfyui_success_saves_image_and_completes_exact_job_state() -> None:
    harness = Harness()
    job = base_job()

    run(job, request(prompt="рисунок"), harness)

    assert job["status"] == "completed"
    assert job["resultImageId"] == "img_worker_1"
    assert job["gallerySaveStatus"] == "saved"
    assert job["galleryQuota"]["gallery_used"] == 1
    assert [item[0] for item in harness.events] == [
        "persist",
        "sleep",
        "persist",
        "comfyui",
        "quota",
        "save",
        "quota",
        "persist",
    ]
    assert [item["status"] for item in harness.persisted] == ["uploading", "sent_to_comfyui", "completed"]
    assert harness.saved[0]["promptTranslated"] == ""
    assert harness.saved[0]["comfyuiPromptId"] == "prompt_1"
    assert harness.saved[0]["generationTimeMs"] == 2250


def test_full_favorite_protected_gallery_keeps_transient_result_without_db_save() -> None:
    harness = Harness()
    harness.quota_values = [
        {"gallery_full": True, "gallery_used": 1, "gallery_slots": 1},
        {"gallery_full": True, "gallery_used": 1, "gallery_slots": 1},
    ]
    job = base_job()

    run(job, request(), harness)

    assert job["status"] == "completed"
    assert job["resultImageId"] is None
    assert job["gallerySaveStatus"] == "quota_full"
    assert harness.saved == []
    assert [item["id"] for item in harness.transient] == ["img_worker_1"]
    assert ("evict", "user_1", 1, "2026-07-14T00:00:00+00:00") in harness.events


def test_openrouter_success_applies_settlement_and_provider_metadata() -> None:
    harness = Harness()
    job = base_job(provider="openrouter")
    job["openrouterBilling"] = {"chargedTokens": 7}

    run(job, request(provider="openrouter"), harness)

    assert job["status"] == "completed"
    assert job["tokenCost"] == 2
    assert job["tokenAdjustment"] == {"settled": 2, "refund": 5, "adjusted": True}
    assert job["openrouterBilling"] == {"actualTokens": 3, "chargedTokens": 7}
    assert job["openrouterModel"] == "provider/model"
    assert harness.saved[0]["width"] == 1024
    assert harness.saved[0]["openrouterResponseId"] == "response_1"
    assert "comfyui" not in [item[0] for item in harness.events]


def test_missing_comfyui_result_without_fallback_fails_and_refunds() -> None:
    harness = Harness()
    harness.comfy_result = None
    harness.mock_fallback = False
    job = base_job()

    run(job, request(), harness)

    assert job["status"] == "failed"
    assert job["error"] == "ComfyUI не вернул изображение, mock fallback отключён."
    assert harness.refunds == [("job_1", "generation_failed")]
    assert "mock" not in [item[0] for item in harness.events]
    assert harness.persisted[-1]["status"] == "failed"


def test_provider_exception_fails_and_refunds_once() -> None:
    harness = Harness()
    harness.provider_error = RuntimeError("provider unavailable")
    job = base_job()

    run(job, request(), harness)

    assert job["status"] == "failed"
    assert job["error"] == "provider unavailable"
    assert harness.refunds == [("job_1", "generation_failed")]
    assert harness.persisted[-1]["status"] == "failed"


def test_cancellation_during_mock_progress_refunds_without_saving() -> None:
    harness = Harness()
    harness.comfy_result = None
    harness.mock_fallback = True
    harness.cancel_on_sleep = 0.45
    job = base_job()
    harness.cancel_job = job

    run(job, request(), harness)

    assert job["status"] == "cancelled"
    assert job["progress"] == 38
    assert harness.refunds == [("job_1", "cancelled_during_generation")]
    assert harness.saved == []
    assert "mock" not in [item[0] for item in harness.events]
    assert harness.persisted[-1]["status"] == "cancelled"
