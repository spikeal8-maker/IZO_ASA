"""HTTP boundary for a separately deployed Qwen3-ASR service."""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx


DEFAULT_QWEN_ASR_BASE_URL = "http://127.0.0.1:8001"
DEFAULT_QWEN_ASR_MODEL = "Qwen/Qwen3-ASR-1.7B"


def qwen_asr_base_url(value: str | None = None) -> str:
    return (value if value is not None else os.getenv("QWEN_ASR_BASE_URL", DEFAULT_QWEN_ASR_BASE_URL)).rstrip("/")


async def fetch_qwen_asr_status(
    *,
    base_url: str | None = None,
    timeout_seconds: float = 2,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Probe the OpenAI-compatible model endpoint exposed by vLLM."""

    resolved_base_url = qwen_asr_base_url(base_url)
    options: dict[str, Any] = {"timeout": timeout_seconds}
    if transport is not None:
        options["transport"] = transport
    try:
        async with httpx.AsyncClient(**options) as client:
            response = await client.get(f"{resolved_base_url}/v1/models")
        response.raise_for_status()
        payload = response.json() if response.content else {}
        models = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), list) else []
        return {"ok": True, "baseUrl": resolved_base_url, "models": models}
    except Exception as exc:
        return {"ok": False, "baseUrl": resolved_base_url, "models": [], "error": type(exc).__name__}


def _message_text(payload: Any) -> str:
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict)
        ).strip()
    return ""


async def request_qwen_asr_transcription(
    *,
    audio: bytes,
    audio_format: str,
    language: str,
    model: str = DEFAULT_QWEN_ASR_MODEL,
    base_url: str | None = None,
    timeout_seconds: float = 45,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[str, dict[str, Any]]:
    """Transcribe one recording through Qwen3-ASR's chat-completions API."""

    resolved_base_url = qwen_asr_base_url(base_url)
    mime = {
        "wav": "audio/wav",
        "webm": "audio/webm",
        "ogg": "audio/ogg",
        "m4a": "audio/mp4",
        "mp3": "audio/mpeg",
    }.get(audio_format, "audio/wav")
    body = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": f"Transcribe the {language} speech exactly. Return only the transcript."},
                {
                    "type": "audio_url",
                    "audio_url": {"url": f"data:{mime};base64,{base64.b64encode(audio).decode('ascii')}"},
                },
            ],
        }],
        "temperature": 0,
        "max_tokens": 1000,
    }
    options: dict[str, Any] = {"timeout": timeout_seconds}
    if transport is not None:
        options["transport"] = transport
    async with httpx.AsyncClient(**options) as client:
        response = await client.post(f"{resolved_base_url}/v1/chat/completions", json=body)
    payload = response.json() if response.content else {}
    if response.status_code >= 400:
        raise RuntimeError(f"Qwen ASR вернул ошибку {response.status_code}.")
    text = _message_text(payload)
    if not text:
        raise RuntimeError("Qwen ASR не распознал речь.")
    return text[:2000], payload if isinstance(payload, dict) else {}
