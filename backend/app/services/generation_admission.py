"""Atomic generation admission and immutable owner-scoped acceptance replay.

The existing jobs primary key serializes requests without a schema change.
Replay survives restart and terminal persistence while the job and its private
metadata remain present. Missing/corrupt metadata fails closed; GET /api/jobs
continues to provide current progress rather than this original response.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import sqlite3
from typing import Any
import uuid

from ..security.trial_access import reserve_or_charge_generation
from . import generation_jobs

_ACCEPTED_FIELDS = frozenset({
    "id", "userId", "mode", "provider", "status", "progress", "message",
    "tokenCost", "openrouterBilling", "createdAt", "trialAccess", "queuePosition",
    "usedDailyBudget", "tokenBalance", "mainBalanceTokens", "dailyTokenPart",
    "mainBalanceTokenPart", "dailyTokensUsed", "dailyTokensLimit", "dailyTokensRemaining",
})


class AdmissionError(RuntimeError):
    def __init__(self, status_code: int, detail: Any):
        super().__init__("GENERATION_ADMISSION_REJECTED")
        self.status_code, self.detail = status_code, detail


@dataclass(frozen=True)
class AdmissionRuntime:
    connect: Callable[[], sqlite3.Connection]
    jobs: MutableMapping[str, dict[str, Any]]
    queue: Any
    require_generation_social_verification: Callable[..., None]
    plan_order: Any
    resolution_id_for_size: Callable[..., Any]
    normalize_resolution_ids: Callable[..., Any]
    get_tariff_config: Callable[..., Any]
    config_ui_resolution_ids: Any
    openrouter_generation_modes: Any
    fetch_openrouter_image_capabilities: Callable[..., Any]
    resolve_openrouter_model: Callable[..., Any]
    get_openrouter_config: Callable[..., Any]
    openrouter_model_allowed: Callable[..., Any]
    supported_resolution_ids_from_capability: Callable[..., Any]
    estimate_openrouter_billing: Callable[..., Any]
    estimate_token_cost: Callable[..., int]
    validate_edit_request: Callable[..., None]
    outpaint_padding: Callable[..., Any]
    validate_generation_media_inputs: Callable[..., None]
    ensure_rate_limit: Callable[[str], None]
    charge_generation_tokens: Callable[..., dict[str, Any]]
    record_event_log: Callable[..., None]


def _identity(user_id: str, key: str | None, data: dict[str, Any]) -> tuple[str | None, str | None]:
    if key is None:
        return None, None
    if not isinstance(key, str) or not 1 <= len(key) <= 128 or any(not 33 <= ord(c) <= 126 for c in key):
        raise AdmissionError(400, "Idempotency-Key must contain 1 to 128 visible ASCII characters.")
    encoded = json.dumps(["IZO/generation/idempotency/v1", user_id, key], separators=(",", ":"))
    job_id = generation_jobs.ADMISSION_JOB_PREFIX + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    fingerprint = hashlib.sha256(("IZO/generation/request/v1\0" + canonical).encode("utf-8")).hexdigest()
    return job_id, fingerprint


def _replay(conn, user_id: str, job_id: str | None, fingerprint: str | None) -> dict[str, Any] | None:
    if job_id is None:
        return None
    row = conn.execute("SELECT id, user_id, settings_json FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    unavailable = "The original generation acceptance is unavailable."
    if row["user_id"] != user_id:
        raise AdmissionError(409, unavailable)
    try:
        settings = json.loads(row["settings_json"])
        metadata = settings[generation_jobs.ADMISSION_METADATA_KEY]
        if not isinstance(metadata, dict) or type(metadata.get("version")) is not int or metadata["version"] != 1:
            raise ValueError("metadata")
        stored = metadata["requestFingerprint"]
        if not isinstance(stored, str) or len(stored) != 64:
            raise ValueError("fingerprint")
        if stored != fingerprint:
            raise AdmissionError(409, "Idempotency-Key cannot be reused for a different generation request.")
        response = metadata["acceptedResponse"]
        if (not isinstance(response, dict) or not set(response) <= _ACCEPTED_FIELDS
                or not (_ACCEPTED_FIELDS - {"trialAccess"}) <= set(response)
                or response.get("id") != job_id or response.get("userId") != user_id
                or response.get("status") != "queued"):
            raise ValueError("acceptance")
        return response
    except (ValueError, TypeError, KeyError):
        raise AdmissionError(409, unavailable) from None


def _cached(runtime, user_id, job_id, fingerprint):
    if job_id is None:
        return None
    with closing(runtime.connect()) as conn:
        return _replay(conn, user_id, job_id, fingerprint)


def preprod216_personal_gallery_limits(conn: sqlite3.Connection, user_id: str,
                                       plan: str) -> tuple[int, int] | None:
    """Single migration-only owner grant; never change the global plan matrix."""
    if os.getenv("IZO_PREPROD_PRESERVE_HISTORY") != "1" or plan != "pro":
        return None
    try:
        rows = conn.execute(
            "SELECT user_id,gallery_slots,video_slots FROM "
            "preprod216_owner_gallery_overrides"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return None
        raise
    if len(rows) > 1:
        raise RuntimeError("PREPROD216_MULTIPLE_OWNER_OVERRIDES_FORBIDDEN")
    if not rows:
        return None
    owner, images, videos = rows[0]
    if (int(images), int(videos)) != (120, 15):
        raise RuntimeError("PREPROD216_UNAPPROVED_PERSONAL_QUOTA")
    return (120, 15) if str(owner) == str(user_id) else None


def _ensure_preprod_gallery_slot(conn: sqlite3.Connection, runtime: AdmissionRuntime,
                                 user_id: str) -> None:
    """Do not charge or queue a new image that would evict historic owner media."""
    if os.getenv("IZO_PREPROD_PRESERVE_HISTORY") != "1":
        return
    row = conn.execute("SELECT plan FROM users WHERE id=?", (user_id,)).fetchone()
    if row is None:
        raise AdmissionError(404, "User not found.")
    plan = str(row["plan"] or "mini").lower()
    if plan not in runtime.plan_order:
        plan = "mini"
    limit = int(runtime.get_tariff_config()[plan].get("gallery_slots") or 0)
    owner_limits = preprod216_personal_gallery_limits(conn, user_id, plan)
    if owner_limits is not None:
        limit = owner_limits[0]
    used = conn.execute(
        "SELECT COUNT(*) FROM images WHERE user_id=? "
        "AND (deleted_at IS NULL OR deleted_at='')", (user_id,)
    ).fetchone()[0]
    pending = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE user_id=? "
        "AND mode IN ('text_to_image','image_to_image','edit','paint','inpaint',"
        "'outpaint','faceswap','remove_background') "
        "AND status IN ('queued','running','pending','in_progress',"
        "'submitting','finalizing','processing')", (user_id,)
    ).fetchone()[0]
    if limit <= 0 or used + pending >= limit:
        raise AdmissionError(409, "GALLERY_QUOTA_FULL_HISTORY_PRESERVED")


async def _prepare(req, user_id: str, runtime: AdmissionRuntime) -> tuple[int, dict[str, Any] | None]:
    openrouter_billing: dict[str, Any] | None = None
    with closing(runtime.connect()) as conn:
        user_row = conn.execute("SELECT id, plan FROM users WHERE id = ?", (user_id,)).fetchone()
        if user_row is None:
            raise AdmissionError(404, "User not found.")
    plan = str(user_row["plan"] or "mini").lower()
    if plan not in runtime.plan_order:
        plan = "mini"
    requested_resolution_id = runtime.resolution_id_for_size(req.width, req.height)
    dynamic_local_editor_size = (
        req.provider == "comfyui"
        and req.mode in {"outpaint", "inpaint", "remove_background"}
        and requested_resolution_id is None
    )
    if dynamic_local_editor_size:
        normalized_base_ids = runtime.normalize_resolution_ids([req.resolutionId] if req.resolutionId else [])
        requested_resolution_id = normalized_base_ids[0] if normalized_base_ids else None
        safe_dynamic_size = (
            req.width % 16 == 0
            and req.height % 16 == 0
            and 512 <= req.width <= 1792
            and 512 <= req.height <= 1792
            and req.width * req.height <= 2_050_000
        )
        if not safe_dynamic_size:
            raise AdmissionError(422, "Размер изображения редактора выходит за безопасные пределы локальной модели.")
    if requested_resolution_id is None:
        raise AdmissionError(422, "Выбран нестандартный размер изображения. Выберите доступное разрешение в интерфейсе.")
    if requested_resolution_id not in runtime.get_tariff_config()[plan]["allowed_resolutions"]:
        raise AdmissionError(403, "Это разрешение недоступно на вашем тарифе.")
    if req.provider == "comfyui":
        if requested_resolution_id not in runtime.config_ui_resolution_ids:
            raise AdmissionError(422, "Это разрешение ещё не подтверждено для серверной модели.")
    if req.provider == "openrouter":
        if req.mode not in runtime.openrouter_generation_modes:
            raise AdmissionError(501, "OpenRouter для этой вкладки пока не подключён.")
        if req.mode == "image_to_image" and not req.inputImage1:
            raise AdmissionError(400, "Для режима «По фото» требуется исходное изображение.")
        if req.mode == "edit":
            references = [item for item in req.inputImages if item.image]
            capabilities = await runtime.fetch_openrouter_image_capabilities()
            resolved_model = runtime.resolve_openrouter_model(req)
            capability = next((item for item in capabilities if item.get("id") == resolved_model), None)
            if capability is None or "edit" not in (capability.get("modes") or []):
                raise AdmissionError(400, "Выбранная модель не поддерживает «Сборку» из нескольких изображений.")
            reference_limit = min(4, int(capability.get("maxInputReferences") or 0))
            if len(references) < 2:
                raise AdmissionError(400, "Для «Сборки» нужны основа и хотя бы один референс.")
            if len(references) > reference_limit:
                raise AdmissionError(400, f"Выбранная модель принимает не больше {reference_limit} изображений.")
        openrouter_config = runtime.get_openrouter_config()
        if not runtime.openrouter_model_allowed(openrouter_config, req.mode, plan, req.modelProfile):
            raise AdmissionError(403, "This OpenRouter model is not available for this mode and tariff.")
        capabilities = await runtime.fetch_openrouter_image_capabilities()
        resolved_model = runtime.resolve_openrouter_model(req)
        capability = next((item for item in capabilities if item.get("id") == resolved_model), None)
        if req.mode != "text_to_image" and (
            capability is None or req.mode not in (capability.get("modes") or [])
        ):
            raise AdmissionError(400, "Выбранная модель не поддерживает этот режим генерации.")
        if requested_resolution_id not in runtime.supported_resolution_ids_from_capability(capability):
            raise AdmissionError(422, "Выбранное разрешение не поддерживается этой моделью.")
        openrouter_billing = await runtime.estimate_openrouter_billing(req, capability)
        token_cost = int(openrouter_billing["chargedTokens"])
    else:
        token_cost = runtime.estimate_token_cost(req)
    # FaceSwap lora auto-selection is handled by choose_faceswap_lora() inside
    # send_to_comfyui (worker). Early validation here is redundant and breaks
    # the flow when frontend sends an empty loras list — the worker always
    # resolves the correct face lora from ComfyUI's available models.
    if req.mode == "edit":
        runtime.validate_edit_request(req)
    if req.mode == "outpaint" and not any(runtime.outpaint_padding(req.outpaint or {}).values()):
        raise AdmissionError(422, "Задайте ненулевое поле расширения слева, справа, сверху или снизу.")
    runtime.validate_generation_media_inputs(req, user_id)
    return token_cost, openrouter_billing


def _accepted(job, token_cost, token_charge, queue_position):
    response = {k: v for k, v in job.items() if k != "request"} | {
        "queuePosition": queue_position,
        "tokenCost": token_cost,
        "usedDailyBudget": token_charge["used_daily"],
        "tokenBalance": token_charge["new_balance"],
        "mainBalanceTokens": token_charge["new_balance"],
        "dailyTokenPart": token_charge["daily_part"],
        "mainBalanceTokenPart": token_charge["balance_part"],
        "dailyTokensUsed": token_charge["daily_tokens_used"],
        "dailyTokensLimit": token_charge["daily_tokens_limit"],
        "dailyTokensRemaining": token_charge["daily_tokens_remaining"],
    }
    return json.loads(json.dumps(response, ensure_ascii=False))


async def admit(req, trusted: Mapping[str, Any], key: str | None, runtime: AdmissionRuntime) -> dict[str, Any]:
    """Accept once under the writer lock; only a new committed job is woken."""
    user_id, internal_user_id = str(trusted["legacy_user_id"]), str(trusted["internal_user_id"])
    data = req.model_dump()
    # The request DTO is validated by the route; this reserved key is never input.
    data.pop(generation_jobs.ADMISSION_METADATA_KEY, None)
    data.pop(generation_jobs.WORKER_CLAIM_METADATA_KEY, None)
    job_id, fingerprint = _identity(user_id, key, data)
    replay = _cached(runtime, user_id, job_id, fingerprint)
    if replay is not None:
        return replay
    try:
        runtime.require_generation_social_verification(trusted, req)
        token_cost, billing = await _prepare(req, user_id, runtime)
    except Exception:
        # Another identical request may commit while asynchronous preflight runs.
        replay = _cached(runtime, user_id, job_id, fingerprint)
        if replay is not None:
            return replay
        raise
    job_id = job_id or f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    job = {
        "id": job_id, "userId": user_id, "mode": req.mode, "provider": req.provider,
        "status": "queued", "progress": 0, "message": "В очереди", "request": data,
        "tokenCost": token_cost, "openrouterBilling": billing,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    with closing(runtime.connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        replay = _replay(conn, user_id, job_id if fingerprint is not None else None, fingerprint)
        if replay is not None:
            return replay
        runtime.require_generation_social_verification(trusted, req)
        runtime.ensure_rate_limit(user_id)
        _ensure_preprod_gallery_slot(conn, runtime, user_id)
        charge = reserve_or_charge_generation(
            conn, internal_user_id, job_id, now=datetime.now(timezone.utc).isoformat(), job=job,
            charge=lambda: runtime.charge_generation_tokens(conn, user_id, token_cost, job_id, req, billing),
            denied=lambda detail: AdmissionError(403, detail),
        )
        response = _accepted(job, token_cost, charge, runtime.queue.qsize() + 1)
        metadata = None if fingerprint is None else {
            "version": 1, "requestFingerprint": fingerprint, "acceptedResponse": response,
        }
        generation_jobs.persist_runtime_job(
            conn, job, request_data=dict(data), now_iso=datetime.now(timezone.utc).isoformat(),
            admission_metadata=metadata,
        )
    runtime.jobs[job_id] = job
    await runtime.queue.put(job_id)
    try:
        runtime.record_event_log(
            "generation_started", internal_user_id=internal_user_id, legacy_user_id=user_id,
            session_id=trusted.get("session_id"), platform=trusted.get("platform", "web"),
            properties={"mode": req.mode, "provider": req.provider, "size": f"{req.width}x{req.height}",
                        "token_cost": token_cost, "openrouter_billing": billing},
        )
    except Exception:
        pass
    return response
