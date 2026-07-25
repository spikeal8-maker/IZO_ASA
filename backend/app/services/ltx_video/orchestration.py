from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .client import ComfyLtxClient
from .profiles import LtxProfile, estimate_local_ltx_billing
from .workflow import build_ltx_prompt


class LocalLtxRequestError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


# The LTX 2.3 GGUF stack crashes natively (access violation in torch c10) when
# ComfyUI has to emergency-unload weights at the VAE stage, so a job may start
# only when the card has room for the whole pipeline, not merely a GPU present.
LOCAL_LTX_MIN_FREE_VRAM_BYTES = 20 * 1024**3


async def validate_and_submit_local_ltx_job(
    req: Any,
    *,
    user_id: str,
    profile: LtxProfile,
    workflow_path: Path,
    client: ComfyLtxClient,
    **callbacks: Any,
) -> dict[str, Any]:
    if req.mode != "text_to_video":
        raise LocalLtxRequestError(422, "Локальный LTX пока поддерживает только генерацию по тексту.")
    if req.generateAudio:
        raise LocalLtxRequestError(422, "Локальный LTX пока работает без генерации звука.")
    if req.duration not in profile.durations:
        raise LocalLtxRequestError(422, "Локальный LTX поддерживает ролики длительностью 2 или 4 секунды.")
    if req.resolution != "480p" or req.aspectRatio != "16:9":
        raise LocalLtxRequestError(422, "Локальный LTX сейчас работает в формате 16:9, 480p.")
    if not workflow_path.is_file():
        raise LocalLtxRequestError(503, "Серверный workflow LTX 2.3 не установлен.")
    with callbacks["open_db"]() as conn:
        active = conn.execute(
            """
            SELECT id
            FROM jobs
            WHERE provider='local_ltx'
              AND status IN ('submitting','queued','pending','in_progress','finalizing')
            LIMIT 1
            """
        ).fetchone()
    if active is not None:
        raise LocalLtxRequestError(
            409,
            "Локальный LTX уже выполняет другое видео. Дождитесь завершения текущего задания.",
        )
    free_image_memory = callbacks.pop("free_image_memory", None)
    if free_image_memory is not None:
        # Best effort: the image ComfyUI keeps its models resident between
        # jobs, and that resident VRAM is exactly what starves the video VAE.
        try:
            await free_image_memory()
        except Exception:
            pass
    readiness = await client.readiness()
    if not readiness.get("ready"):
        reason = readiness.get("error") or "GPU не готов"
        raise LocalLtxRequestError(503, f"Локальный LTX недоступен: {reason}")
    vram_free = readiness.get("vramFree")
    if isinstance(vram_free, (int, float)) and vram_free < LOCAL_LTX_MIN_FREE_VRAM_BYTES:
        raise LocalLtxRequestError(
            503,
            "Локальному LTX сейчас не хватает свободной видеопамяти. "
            "Дождитесь завершения текущих генераций и попробуйте снова.",
        )
    return await submit_local_ltx_job(
        req,
        user_id=user_id,
        profile=profile,
        workflow_path=workflow_path,
        client=client,
        **callbacks,
    )


async def submit_local_ltx_job(
    req: Any,
    *,
    user_id: str,
    profile: LtxProfile,
    workflow_path: Path,
    client: ComfyLtxClient,
    open_db: Callable[[], Any],
    reserve_storage: Callable[[Any, Any, str], Any],
    charge_tokens: Callable[..., dict[str, Any]],
    refund_tokens: Callable[..., bool],
) -> dict[str, Any]:
    billing = estimate_local_ltx_billing(profile, duration=req.duration)
    job_id = f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    prompt = build_ltx_prompt(
        workflow_path,
        profile=profile,
        text=req.prompt,
        duration=req.duration,
        filename_prefix=f"izo_ltx/{job_id}",
    )
    now = datetime.now(timezone.utc).isoformat()
    try:
        with open_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            locked_user = conn.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            reserve_storage(conn, locked_user, user_id)
            charge = charge_tokens(
                conn,
                user_id,
                int(billing["chargedTokens"]),
                job_id,
                req,
                billing,
            )
            settings = {
                "model": req.model,
                "localLtxProfile": profile.model_id,
                "duration": req.duration,
                "resolution": req.resolution,
                "aspectRatio": req.aspectRatio,
                "generateAudio": False,
                "tokenCost": billing["chargedTokens"],
                "localLtxBilling": billing,
            }
            conn.execute(
                "INSERT INTO jobs "
                "(id,user_id,mode,provider,status,progress,prompt_original,settings_json,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    user_id,
                    req.mode,
                    "local_ltx",
                    "submitting",
                    5,
                    req.prompt.strip(),
                    json.dumps(settings, ensure_ascii=False),
                    now,
                ),
            )
        prompt_id = await client.submit(prompt, client_id=job_id)
    except Exception:
        with open_db() as conn:
            refund_tokens(conn, job_id, reason="video_submit_failed")
            conn.execute(
                "UPDATE jobs SET status='failed',progress=100,error_message=?,completed_at=? WHERE id=?",
                (
                    "Не удалось запустить локальный LTX.",
                    datetime.now(timezone.utc).isoformat(),
                    job_id,
                ),
            )
        raise
    with open_db() as conn:
        row = conn.execute(
            "SELECT settings_json FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone()
        settings = json.loads(row["settings_json"]) if row else {}
        settings["comfyPromptId"] = prompt_id
        conn.execute(
            "UPDATE jobs SET status='queued',progress=10,settings_json=? WHERE id=?",
            (json.dumps(settings, ensure_ascii=False), job_id),
        )
    return {
        "id": job_id,
        "status": "queued",
        "progress": 10,
        "tokenCost": billing["chargedTokens"],
        "tokenBalance": charge["new_balance"],
    }
