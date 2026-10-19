"""Controlled ASR/TTS wire extension; fixed synthetic tones, no voice/model execution."""
from __future__ import annotations

import base64
import hashlib
import io
import secrets
import struct
import uuid
import wave
import zlib

try:
    from tools.docker_shadow_provider import ControlledProvider, RequestError
except ModuleNotFoundError:
    from docker_shadow_provider import ControlledProvider, RequestError

MARKER = "controlled-audio-v1"
ASR_MODEL = "d3-protocol-asr"
ASR_CASES = ("wav", "ogg", "upstream_failure", "empty")
TRANSCRIPTS = {"wav": "Controlled WAV transcript.", "ogg": "Controlled OGG transcript."}
SPEECH_CASES = (("irina", -1), ("pavel", 2), ("failure", 0))
CANARY = "http://127.0.0.1:48991/private/D3_CANARY /srv/private/D3_CANARY C:\\private\\D3_CANARY"
# Generated Ogg/FLAC from wave_bytes(2, 16000), then losslessly compressed for source storage.
# This is valid non-WAV audio; its decoded PCM must survive the application's real ffmpeg conversion.
OGG = zlib.decompress(base64.b64decode(
    'eNrt2ssrRFEcB/DfcS/GY0gi2XhsFBl3Zpoxjec0ZTXlFitlMQ1jI6TIwuOGkg1blOUs7S34CyQbUkopzxU2ipTr/q7nHRYWqFPf'
    '2z3N43fOp+lX35p7Op0DA12UQa/XwnLpNL+2pJQn4Z/piEWigkgkY/Go9W21aqgGl3NKlCu6pW+uTuboM2etp6nZehKN80R+t/Up'
    'Fh9PBjWPN+jxahqXy63RP5QY7usfbbGKCavo91pFX2VyMJ6wSdVo/SD55x5sPFSHTNPcfR17P3j/NvrM+4CLlEjb3GXYI8YOex03'
    'Kdeh06XPN9GNc8qhTq3OKaETKrgDBAjQ/0H6ZBcnWah2kjWBlgECJCOkrwxzkjPcdpLrBVoGCJCcEK1rnGUlN1I5dRluEBOOVQY1'
    'pS3Zp8LNNJiU7bR/5e306JwCCBCgv4WM8zNOslphJ1l7TzJaBgiQTJBRHOUkZ5bZSa6zkoyWAQIkI9Qe9nKWs4q+7HrhGQUQIHkg'
    '/aiKk5xdaie5QaBlgADJCOkjW5xkV9Pb/jVaBgiQlBClujnLOc1pu154RgEESCbIWN3kJOcG7CR7XpKMlgECJBt0TJzkPB/ObAIC'
    'JPOZzZ01TnJ+Dc5sAgIk85nNo2nzPuVyL9pJrsWZTUCAfhM66bl4BgmRTWo='
))


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def wave_bytes(marker: int, rate: int = 8000) -> bytes:
    if marker not in range(1, 7) or rate not in (8000, 16000):
        raise ValueError("D3_AUDIO_SAMPLE_INVALID")
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(b"".join(struct.pack("<h", 1000 if (index // (20 + marker)) % 2 else -1000)
                                 for index in range(rate)))
    return output.getvalue()


def wave_facts(content: bytes) -> dict:
    try:
        if not isinstance(content, bytes) or not 44 < len(content) <= 65536:
            raise ValueError
        with wave.open(io.BytesIO(content), "rb") as audio:
            channels, width, rate, frames = (audio.getnchannels(), audio.getsampwidth(),
                                             audio.getframerate(), audio.getnframes())
            if channels != 1 or width != 2 or rate not in (8000, 16000) or frames != rate:
                raise ValueError
            pcm = audio.readframes(frames)
            if len(pcm) != frames * 2 or not any(pcm):
                raise ValueError
        return {"bytes": len(content), "sha256": digest(content), "pcmSha256": digest(pcm),
                "channels": channels, "sampleWidth": width, "sampleRate": rate, "frames": frames}
    except (ValueError, EOFError, wave.Error):
        raise RequestError() from None


def speech_request(case: str) -> dict:
    allowed = dict(SPEECH_CASES)
    if case not in allowed:
        raise ValueError("D3_AUDIO_SPEECH_CASE_INVALID")
    return {"text": "D3 audio protocol: " + case, "voice": "irina" if case == "failure" else case,
            "rate": allowed[case]}


class AudioProvider(ControlledProvider):
    """Uses the existing two owned loopback listeners, body/deadline/4-request bounds."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.instance_id = uuid.uuid4().hex
        self.speech_token = secrets.token_urlsafe(32)
        self._asr, self._speech = [], []
        self._samples = {case: wave_facts(wave_bytes(index, 16000 if case == "ogg" else 8000))
                         for index, case in enumerate(ASR_CASES, 1)}

    def receipt(self):
        value = super().receipt()
        with self._lock:
            value["audio"] = {"profile": MARKER, "instanceId": self.instance_id,
                "lifetimeSeconds": self._lifetime, "modelExecution": False, "acceleratorExecution": False,
                "waveform": "SYNTHETIC_TONE", "asr": [dict(row) for row in self._asr],
                "speech": [dict(row) for row in self._speech]}
        return value

    def _transcribe(self, headers, body):
        if len(body) > 65536:
            raise RequestError(413)
        payload = self._json(headers, body)
        messages = payload.get("messages")
        if (set(payload) != {"model", "messages", "temperature", "max_tokens"}
                or payload["model"] != ASR_MODEL or type(payload["temperature"]) is not int
                or payload["temperature"] != 0 or type(payload["max_tokens"]) is not int or payload["max_tokens"] != 1000
                or not isinstance(messages, list) or len(messages) != 1
                or not isinstance(messages[0], dict) or set(messages[0]) != {"role", "content"}
                or messages[0]["role"] != "user"):
            raise RequestError()
        content = messages[0]["content"]
        expected_text = "Transcribe the Russian speech exactly. Return only the transcript."
        if (not isinstance(content, list) or len(content) != 2 or content[0] != {"type": "text", "text": expected_text}
                or not isinstance(content[1], dict) or set(content[1]) != {"type", "audio_url"}
                or content[1]["type"] != "audio_url" or not isinstance(content[1]["audio_url"], dict)
                or set(content[1]["audio_url"]) != {"url"}):
            raise RequestError()
        url = content[1]["audio_url"]["url"]
        if not isinstance(url, str) or not url.startswith("data:audio/wav;base64,"):
            raise RequestError()
        facts = wave_facts(base64.b64decode(url.split(",", 1)[1], validate=True))
        case = next((name for name, expected in self._samples.items()
                     if facts["pcmSha256"] == expected["pcmSha256"] and facts["sampleRate"] == expected["sampleRate"]), None)
        with self._lock:
            if len(self._asr) >= len(ASR_CASES) or case != ASR_CASES[len(self._asr)]:
                raise RequestError(409)
            status = 503 if case == "upstream_failure" else 200
            self._asr.append({"case": case, "requestSha256": digest(body), "httpStatus": status, "wave": facts})
        if status == 503:
            return status, {"error": CANARY}, "application/json"
        return 200, {"choices": [{"message": {"content": TRANSCRIPTS.get(case, "")}}],
                     "usage": {"prompt_tokens": 0, "completion_tokens": 0}}, "application/json"

    def _speak(self, headers, body):
        authorization = str(headers.get("authorization", "")).encode("utf-8")
        if not secrets.compare_digest(authorization, ("Bearer " + self.speech_token).encode("ascii")):
            raise RequestError(401)
        if len(body) > 32768:
            raise RequestError(413)
        payload = self._json(headers, body)
        if type(payload.get("rate")) is not int:
            raise RequestError()
        case = next((name for name, _rate in SPEECH_CASES if payload == speech_request(name)), None)
        with self._lock:
            if len(self._speech) >= len(SPEECH_CASES) or case != SPEECH_CASES[len(self._speech)][0]:
                raise RequestError(409)
            status = 503 if case == "failure" else 200
            output = wave_bytes(5 if case == "irina" else 6) if status == 200 else b""
            self._speech.append({"case": case, "requestSha256": digest(body), "httpStatus": status,
                "voice": payload["voice"], "rate": payload["rate"], "textSha256": digest(payload["text"].encode()),
                "wave": wave_facts(output) if output else None})
        return (status, output, "audio/wav") if output else (status, {"error": CANARY}, "application/json")

    def _provider(self, method, target, headers, body):
        if method == "POST" and target == "/v1/chat/completions":
            self._count("audio_asr_requests")
            return self._transcribe(headers, body)
        if method == "POST" and target == "/v1/speech":
            self._count("audio_speech_requests")
            return self._speak(headers, body)
        return super()._provider(method, target, headers, body)
