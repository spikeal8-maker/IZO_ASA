"""Local OpenAI-compatible Qwen3-ASR service for the Windows host."""

from __future__ import annotations

import asyncio
import os
import re
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException


MODEL_ID = os.getenv("QWEN_ASR_MODEL", "Qwen/Qwen3-ASR-1.7B")
MODEL_REVISION = os.getenv("QWEN_ASR_MODEL_REVISION", "7278e1e70fe206f11671096ffdd38061171dd6e5")
_model: Any = None
_runtime_info: dict[str, Any] = {"cuda": False, "device": None}
_model_lock = asyncio.Lock()


def _load_model() -> tuple[Any, dict[str, Any]]:
    import torch
    from qwen_asr import Qwen3ASRModel

    if not torch.cuda.is_available():
        raise RuntimeError("Qwen ASR requires the CUDA runtime on this host.")
    torch.set_float32_matmul_precision("high")
    model = Qwen3ASRModel.from_pretrained(
        MODEL_ID,
        revision=MODEL_REVISION,
        dtype=torch.bfloat16,
        device_map="cuda:0",
        max_inference_batch_size=1,
        max_new_tokens=96,
        low_cpu_mem_usage=True,
    )
    return model, {"cuda": True, "device": torch.cuda.get_device_name(0)}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _model, _runtime_info
    _model, _runtime_info = await asyncio.to_thread(_load_model)
    yield
    _model = None
    _runtime_info = {"cuda": False, "device": None}
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


app = FastAPI(title="IZO ASA Qwen3-ASR", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": _model is not None,
        "model": MODEL_ID,
        "revision": MODEL_REVISION,
        **_runtime_info,
    }


@app.get("/v1/models")
async def models() -> dict[str, Any]:
    if _model is None:
        raise HTTPException(503, "Qwen ASR is still loading.")
    return {
        "object": "list",
        "data": [{"id": MODEL_ID, "object": "model", "owned_by": "Qwen", "revision": MODEL_REVISION}],
    }


def _request_audio_and_language(payload: dict[str, Any]) -> tuple[str, str | None]:
    messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
    audio_url = ""
    instruction = ""
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content") if isinstance(message.get("content"), list) else []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                instruction += " " + str(part.get("text") or "")
            if part.get("type") == "audio_url":
                descriptor = part.get("audio_url") if isinstance(part.get("audio_url"), dict) else {}
                audio_url = str(descriptor.get("url") or "")
    if not audio_url:
        raise HTTPException(400, "audio_url is required.")
    language = None
    for candidate in ("Russian", "English"):
        if re.search(rf"\b{candidate}\b", instruction, flags=re.IGNORECASE):
            language = candidate
            break
    return audio_url, language


@app.post("/v1/chat/completions")
async def chat_completions(payload: dict[str, Any]) -> dict[str, Any]:
    if _model is None:
        raise HTTPException(503, "Qwen ASR is still loading.")
    requested_model = str(payload.get("model") or MODEL_ID)
    if requested_model != MODEL_ID:
        raise HTTPException(400, f"Model {requested_model} is not loaded.")
    audio_url, language = _request_audio_and_language(payload)
    started = time.monotonic()
    async with _model_lock:
        results = await asyncio.to_thread(_model.transcribe, audio=audio_url, language=language)
    text = results[0].text.strip() if results else ""
    if not text:
        raise HTTPException(422, "Qwen ASR did not recognize speech.")
    return {
        "id": f"qwen-asr-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "model": MODEL_ID,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"latency_ms": round((time.monotonic() - started) * 1000)},
    }
