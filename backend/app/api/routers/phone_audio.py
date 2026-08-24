"""Authenticated local speech synthesis for the phone workspace."""

from __future__ import annotations

import asyncio
import base64
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask


class PhoneSpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice: Literal["irina", "pavel"] = "irina"
    rate: int = Field(default=0, ge=-5, le=5)


@dataclass(frozen=True)
class PhoneAudioDependencies:
    require_user: Callable[[Request], dict[str, Any]]


_VOICE_NAMES = {
    "irina": "Microsoft Irina Desktop",
    "pavel": "Microsoft Pavel",
}
_speech_semaphore = asyncio.Semaphore(2)


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


def create_phone_audio_router(dependencies: PhoneAudioDependencies) -> APIRouter:
    router = APIRouter(prefix="/api/phone/audio", tags=["phone-audio"])

    @router.post("/speech", response_class=FileResponse)
    async def generate_speech(body: PhoneSpeechRequest, request: Request) -> FileResponse:
        dependencies.require_user(request)
        text = body.text.strip()
        if not text:
            raise HTTPException(400, "Введите текст для озвучивания.")
        handle, output_path = tempfile.mkstemp(prefix="izo-phone-speech-", suffix=".wav")
        os.close(handle)
        _remove_file(output_path)
        try:
            async with _speech_semaphore:
                await asyncio.to_thread(_synthesize_windows_speech, text, body.voice, body.rate, output_path)
        except Exception as exc:
            _remove_file(output_path)
            raise HTTPException(503, "Озвучивание временно недоступно. Повторите позже.") from exc
        return FileResponse(
            output_path,
            media_type="audio/wav",
            filename="izo-asa-voice.wav",
            headers={"Cache-Control": "private, no-store"},
            background=BackgroundTask(_remove_file, output_path),
        )

    return router
