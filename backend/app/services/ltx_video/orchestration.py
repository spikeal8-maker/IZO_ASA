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


def normalize_runtime_settings(
    requested: dict[str, Any], current: dict[str, Any], *, has_active_job: bool
) -> dict[str, Any]:
    profile = str(requested.get("videoProfile") or "local/ltx-2.3-fast-q3")
    if profile not in {"local/ltx-2.3-fast-q3", "local/ltx-2.3-standard-q4"}:
        raise LocalLtxRequestError(422, "Неизвестный профиль локальной видеомодели.")
    current_profile = str(current.get("videoProfile") or "local/ltx-2.3-fast-q3")
    if has_active_job and profile != current_profile:
        raise LocalLtxRequestError(
            409, "Нельзя переключать Q3/Q4 во время активной видеогенерации."
        )
    return {
        "imageEnabled": requested.get("imageEnabled") is not False,
        "videoEnabled": requested.get("videoEnabled") is not False,
        "videoProfile": profile,
    }


def recover_missing_job_state(
    state: dict[str, Any], created_at_value: Any, *, grace_seconds: int = 30 * 60
) -> dict[str, Any] | None:
    if str(state.get("status") or "") != "missing":
        return state
    try:
        created_at = datetime.fromisoformat(str(created_at_value).replace("Z", "+00:00"))
        age_seconds = (datetime.now(timezone.utc) - created_at).total_seconds()
    except (TypeError, ValueError):
        age_seconds = grace_seconds
    if age_seconds < grace_seconds:
        return None
    return {
        "status": "failed",
        "error": (
            "Локальная видеогенерация была потеряна после перезапуска "
            "видеосервиса. Токены возвращены; задачу можно запустить снова."
        ),
    }


async def admin_runtime_status(
    *, client: ComfyLtxClient, enabled: bool, base_url: str, open_db: Callable[[], Any]
) -> dict[str, Any]:
    readiness = await client.readiness()
    with open_db() as conn:
        jobs = [
            dict(row)
            for row in conn.execute(
                "SELECT id,status,progress,created_at FROM jobs "
                "WHERE provider='local_ltx' AND status IN "
                "('submitting','queued','pending','in_progress','finalizing') "
                "ORDER BY created_at"
            ).fetchall()
        ]
    return {
        "video": {
            **readiness,
            "enabled": enabled,
            "base_url": base_url,
            "gpu": readiness.get("device"),
            "active_jobs": jobs,
            "profiles": [
                {"id": "local/ltx-2.3-fast-q3", "label": "Q3 — быстрее"},
                {"id": "local/ltx-2.3-standard-q4", "label": "Q4 — качественнее"},
            ],
            "aspect_ratios": ["16:9", "9:16", "1:1"],
            "resolution": "480p",
        }
    }


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
    if req.resolution != "480p" or req.aspectRatio not in {"16:9", "9:16", "1:1"}:
        raise LocalLtxRequestError(
            422, "Локальный LTX поддерживает 480p в форматах 16:9, 9:16 и 1:1."
        )
    if not workflow_path.is_file():
        raise LocalLtxRequestError(503, "Серверный workflow LTX 2.3 не установлен.")
    with callbacks["open_db"]() as conn:
        active = conn.execute(
            """
            SELECT id,created_at,settings_json
            FROM jobs
            WHERE provider='local_ltx'
              AND status IN ('submitting','queued','pending','in_progress','finalizing')
            LIMIT 1
            """
        ).fetchone()
    if active is not None:
        settings = json.loads(active["settings_json"] or "{}")
        prompt_id = str(settings.get("comfyPromptId") or "")
        if prompt_id:
            try:
                recovered = recover_missing_job_state(
                    await client.status(prompt_id), active["created_at"]
                )
            except Exception:
                recovered = None
            if recovered and recovered.get("status") == "failed":
                with callbacks["open_db"]() as conn:
                    callbacks["refund_tokens"](
                        conn, active["id"], reason="video_lost_after_restart"
                    )
                    conn.execute(
                        "UPDATE jobs SET status='failed',progress=100,error_message=?,"
                        "completed_at=? WHERE id=?",
                        (
                            recovered.get("error"),
                            datetime.now(timezone.utc).isoformat(),
                            active["id"],
                        ),
                    )
                active = None
    if active is not None:
        raise LocalLtxRequestError(
            409,
            "Локальный LTX уже выполняет другое видео. Дождитесь завершения текущего задания.",
        )
    readiness = await client.readiness()
    if not readiness.get("ready"):
        reason = readiness.get("error") or "GPU не готов"
        raise LocalLtxRequestError(503, f"Локальный LTX недоступен: {reason}")
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
        aspect_ratio=req.aspectRatio,
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
