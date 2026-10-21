"""Authenticated local speech synthesis for the phone workspace."""

from __future__ import annotations

import asyncio
import base64
import os
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from ...integrations.phone_speech_http import load_settings, synthesize as synthesize_http


class PhoneSpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice: Literal["irina", "pavel"] = "irina"
    rate: int = Field(default=0, ge=-5, le=5)


@dataclass(frozen=True)
class PhoneAudioDependencies:
    require_user: Callable[[Request], dict[str, Any]]
    audio_config: Callable[[], dict[str, Any]] | None = None
    record_event: Callable[..., None] | None = None


_VOICE_NAMES = {
    "irina": "Microsoft Irina Desktop",
    "pavel": "Microsoft Pavel",
}
_speech_semaphore = asyncio.Semaphore(2)


class PhoneSpeechProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class PhoneSpeechProvider:
    event_name: str
    synthesize: Callable[[str, str, int, str], None]


def _remove_file(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def _synthesize_windows_speech(text: str, voice: str, rate: int, output_path: str) -> None:
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$t=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:IZO_TTS_TEXT));"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$s.SelectVoice($env:IZO_TTS_VOICE);"
        "$s.Rate=[int]$env:IZO_TTS_RATE;"
        "$s.SetOutputToWaveFile($env:IZO_TTS_OUTPUT);"
        "$s.Speak($t);$s.Dispose()"
    )
    env = os.environ.copy()
    env.update({
        "IZO_TTS_TEXT": encoded,
        "IZO_TTS_VOICE": _VOICE_NAMES[voice],
        "IZO_TTS_RATE": str(rate),
        "IZO_TTS_OUTPUT": output_path,
    })
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if completed.returncode != 0 or not Path(output_path).is_file():
        raise RuntimeError((completed.stderr or completed.stdout or "speech synthesis failed")[-1000:])


def _synthesize_fake_speech(text: str, voice: str, rate: int, output_path: str) -> None:
    _ = (text, voice, rate)
    with wave.open(output_path, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 800)


def resolve_phone_speech_provider(
    environment: Mapping[str, str] | None = None,
    *,
    platform_name: str | None = None,
) -> PhoneSpeechProvider:
    source = os.environ if environment is None else environment
    configured = str(source.get("IZO_PHONE_TTS_PROVIDER", "")).strip().lower()
    runtime_platform = os.name if platform_name is None else platform_name
    if not configured:
        if runtime_platform == "nt":
            configured = "windows"
        else:
            raise PhoneSpeechProviderError("phone speech provider unavailable")
    if configured == "windows":
        if runtime_platform != "nt":
            raise PhoneSpeechProviderError("phone speech provider unavailable")
        return PhoneSpeechProvider("windows_speech", _synthesize_windows_speech)
    if configured == "fake":
        return PhoneSpeechProvider("fake_speech", _synthesize_fake_speech)
    if configured == "http":
        settings = load_settings(source)
        return PhoneSpeechProvider("windows_speech_http", lambda text, voice, rate, path:
                                   synthesize_http(settings, text, voice, rate, path))
    raise PhoneSpeechProviderError("unsupported phone speech provider")


def create_phone_audio_router(dependencies: PhoneAudioDependencies) -> APIRouter:
    router = APIRouter(prefix="/api/phone/audio", tags=["phone-audio"])

    @router.get("/config")
    async def audio_config(request: Request) -> dict[str, Any]:
        dependencies.require_user(request)
        config = dependencies.audio_config() if dependencies.audio_config is not None else {}
        return {
            "transcriptionPublished": bool(config.get("transcriptionPublished", True)),
            "speechPublished": bool(config.get("speechPublished", True)),
            "voices": [{"id": key, "name": value.replace("Microsoft ", "")} for key, value in _VOICE_NAMES.items()],
            "speechMaxChars": 4000,
            "transcriptionMaxBytes": 8 * 1024 * 1024,
        }

    @router.post("/speech", response_class=FileResponse)
    async def generate_speech(body: PhoneSpeechRequest, request: Request) -> FileResponse:
        trusted = dependencies.require_user(request)
        config = dependencies.audio_config() if dependencies.audio_config is not None else {}
        if not config.get("speechPublished", True):
            raise HTTPException(403, "Озвучивание текста сейчас отключено администратором.")
        text = body.text.strip()
        if not text:
            raise HTTPException(400, "Введите текст для озвучивания.")
        handle, output_path = tempfile.mkstemp(prefix="izo-phone-speech-", suffix=".wav")
        os.close(handle)
        _remove_file(output_path)
        started = time.monotonic()
        try:
            provider = resolve_phone_speech_provider()
            async with _speech_semaphore:
                await asyncio.to_thread(provider.synthesize, text, body.voice, body.rate, output_path)
            if not Path(output_path).is_file():
                raise RuntimeError("speech synthesis failed")
        except Exception as exc:
            _remove_file(output_path)
            raise HTTPException(503, "Озвучивание временно недоступно. Повторите позже.") from exc
        if dependencies.record_event is not None:
            dependencies.record_event(
                "phone_speech_synthesized",
                internal_user_id=trusted.get("internal_user_id"),
                legacy_user_id=trusted.get("legacy_user_id"),
                session_id=trusted.get("session_id"),
                platform="web",
                request=request,
                properties={
                    "provider": provider.event_name,
                    "voice": body.voice,
                    "characters": len(text),
                    "latency_ms": round((time.monotonic() - started) * 1000),
                    "output_bytes": Path(output_path).stat().st_size,
                },
            )
        return FileResponse(
            output_path,
            media_type="audio/wav",
            filename="izo-asa-voice.wav",
            headers={"Cache-Control": "private, no-store"},
            background=BackgroundTask(_remove_file, output_path),
        )

    return router
