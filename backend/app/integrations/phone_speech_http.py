"""Explicit private host speech protocol; never a fallback to fake speech."""
from __future__ import annotations

import hmac
import io
import ipaddress
import json
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

MAX_AUDIO_BYTES = 32 * 1024 * 1024
MAX_REQUEST_BYTES = 32 * 1024


class SpeechHttpError(RuntimeError):
    pass


def private_host(host: str) -> bool:
    if host == "host.docker.internal":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address == ipaddress.ip_address("127.0.0.1") or any(
        address in ipaddress.ip_network(network)
        for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    )


def read_token_file(path: str) -> str:
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(513)
        token = raw.decode("ascii").strip()
        if len(raw) > 512 or not 32 <= len(token) <= 256 or any(
                not (33 <= ord(char) <= 126) for char in token):
            raise ValueError
        return token
    except (OSError, ValueError):
        raise SpeechHttpError("SPEECH_HTTP_SECRET_INVALID") from None


@dataclass(frozen=True)
class SpeechHttpSettings:
    origin: str
    token: str = field(repr=False)


def load_settings(environment: Mapping[str, str]) -> SpeechHttpSettings:
    try:
        value = environment.get("IZO_PHONE_TTS_HTTP_URL", "")
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or not private_host(parsed.hostname) or parsed.port is None
                or not 20000 <= parsed.port <= 65535 or parsed.username or parsed.password
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
            raise ValueError
        origin = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
        token_path = environment.get("IZO_PHONE_TTS_HTTP_TOKEN_FILE", "")
        if not token_path:
            raise ValueError
    except (ValueError, TypeError):
        raise SpeechHttpError("SPEECH_HTTP_CONFIG_INVALID") from None
    return SpeechHttpSettings(origin, read_token_file(token_path))


def valid_input(body: object) -> bool:
    return (isinstance(body, dict) and set(body) == {"text", "voice", "rate"}
            and isinstance(body["text"], str) and 1 <= len(body["text"]) <= 4000 and bool(body["text"].strip())
            and body["voice"] in ("irina", "pavel")
            and type(body["rate"]) is int and -5 <= body["rate"] <= 5)


def validate_wave(content: bytes) -> None:
    try:
        if not 44 < len(content) <= MAX_AUDIO_BYTES:
            raise ValueError
        with wave.open(io.BytesIO(content), "rb") as audio:
            channels, width, rate, frames = (audio.getnchannels(), audio.getsampwidth(),
                                             audio.getframerate(), audio.getnframes())
            if channels not in (1, 2) or width not in (1, 2, 3, 4) or not 8000 <= rate <= 96000:
                raise ValueError
            if not 0 < frames <= rate * 20 * 60 or frames * channels * width > MAX_AUDIO_BYTES:
                raise ValueError
            if len(audio.readframes(frames)) != frames * channels * width:
                raise ValueError
    except (ValueError, EOFError, wave.Error):
        raise SpeechHttpError("SPEECH_HTTP_AUDIO_INVALID") from None


class NoSpeechRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SpeechHttpError("SPEECH_HTTP_REDIRECT_FORBIDDEN")


def synthesize(settings: SpeechHttpSettings, text: str, voice: str, rate: int,
               output_path: str) -> None:
    body = {"text": text, "voice": voice, "rate": rate}
    if not valid_input(body):
        raise SpeechHttpError("SPEECH_HTTP_INPUT_INVALID")
    opener = build_opener(ProxyHandler({}), NoSpeechRedirect())
    request = Request(settings.origin + "/v1/speech", method="POST",
                      data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers={
                          "Content-Type": "application/json",
                          "Authorization": "Bearer " + settings.token,
                      })
    try:
        with opener.open(request, timeout=95) as response:
            if response.status != 200 or response.headers.get_content_type() != "audio/wav":
                raise SpeechHttpError("SPEECH_HTTP_RESPONSE_INVALID")
            content = response.read(MAX_AUDIO_BYTES + 1)
        validate_wave(content)
        Path(output_path).write_bytes(content)
    except HTTPError as error:
        error.close()
        raise SpeechHttpError("SPEECH_HTTP_UNAVAILABLE") from None
    except OSError:
        raise SpeechHttpError("SPEECH_HTTP_UNAVAILABLE") from None


def authorized(value: str, token: str) -> bool:
    # Compare bytes so malformed non-ASCII headers also fail closed.
    return hmac.compare_digest(value.encode("utf-8"), ("Bearer " + token).encode("ascii"))
