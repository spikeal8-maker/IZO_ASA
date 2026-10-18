"""Mounted production audio routes and real loopback HTTP; no speech models/voices."""
from contextlib import contextmanager
from pathlib import Path
import socket
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.routers import phone_audio
from tools.docker_d3_audio_provider import (
    ASR_CASES, ASR_MODEL, AudioProvider, CANARY, OGG, TRANSCRIPTS,
    speech_request, wave_bytes, wave_facts,
)


def unused_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    assert 20000 <= port <= 65535
    return port


@contextmanager
def provider():
    # Addresses are allocated locally, never discovered by scanning an endpoint.
    port, control = unused_port(), unused_port()
    assert port != control
    with AudioProvider(bind="127.0.0.1", port=port, control_port=control, lifetime_seconds=60) as fixture:
        yield fixture
    assert fixture._closed and not fixture._connections


def asr_client(monkeypatch, tmp_path, origin):
    import main
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setattr(main, "require_trusted_user", lambda _request: {
        "internal_user_id": "owned-audio-test", "legacy_user_id": "web-owned-audio-test"})
    monkeypatch.setattr(main, "assistant_models_config", lambda: {"voice": {
        "transcriptionPublished": True, "speechPublished": True, "minRecordingSeconds": 1,
        "route": "qwen", "qwenModel": ASR_MODEL, "qwenBaseUrl": origin, "requestTimeoutSeconds": 10}})
    events = []
    monkeypatch.setattr(main, "record_event_log", lambda *args, **kwargs: events.append((args, kwargs)))
    monkeypatch.setattr(main, "transcribe_audio_openrouter", AsyncMock(side_effect=AssertionError("paid fallback")))
    monkeypatch.setattr(main, "transcribe_audio_ollama", AsyncMock(side_effect=AssertionError("model fallback")))
    original_tempfile = main.tempfile.NamedTemporaryFile
    monkeypatch.setattr(main.tempfile, "NamedTemporaryFile", lambda *args, **kwargs:
                        original_tempfile(*args, **{**kwargs, "dir": tmp_path}))
    app = FastAPI()
    app.add_api_route("/api/tools/transcribe", main.transcribe_audio, methods=["POST"])
    return TestClient(app), events


@pytest.mark.parametrize("kind", [RuntimeError, httpx.ConnectError, httpx.ReadTimeout])
@pytest.mark.parametrize("diagnostic", [CANARY, "qwen: /srv/private/D3_CANARY; local: C:\\private\\D3_CANARY"])
def test_asr_exception_diagnostics_never_reach_the_public_response(monkeypatch, tmp_path, kind, diagnostic):
    import main
    client, events = asr_client(monkeypatch, tmp_path, "http://127.0.0.1:48991")
    monkeypatch.setattr(main, "transcribe_audio_routed", AsyncMock(side_effect=kind(diagnostic)))
    result = client.post("/api/tools/transcribe?duration_ms=1000&language=ru",
        files={"file": ("owned.wav", wave_bytes(1), "audio/wav")})
    assert result.status_code == 502
    assert result.json() == {"detail": "ASR_UNAVAILABLE"}
    assert "D3_CANARY" not in result.text
    assert events == []


def test_real_asr_qwen_http_wav_ogg_errors_and_conversion_cleanup(monkeypatch, tmp_path):
    with provider() as fixture:
        client, events = asr_client(monkeypatch, tmp_path, fixture.base_url)
        existing = set(tmp_path.iterdir())
        for index, case in enumerate(ASR_CASES, 1):
            source, extension = (OGG, "ogg") if case == "ogg" else (wave_bytes(index), "wav")
            result = client.post("/api/tools/transcribe?duration_ms=1000&language=ru",
                files={"file": ("owned." + extension, source, "audio/" + extension)})
            if case in TRANSCRIPTS:
                assert result.status_code == 200
                assert result.json() == {"ok": True, "text": TRANSCRIPTS[case], "provider": "qwen",
                    "model": ASR_MODEL, "usage": {"prompt_tokens": 0, "completion_tokens": 0}, "actualCostUsd": 0.0}
            else:
                assert result.status_code == 502
                assert result.json() == {"detail": "ASR_UNAVAILABLE"}
            assert set(tmp_path.iterdir()) == existing
        invalid = client.post("/api/tools/transcribe?duration_ms=1000&language=ru",
            files={"file": ("owned.ogg", b"OggS-invalid-D3-sample", "audio/ogg")})
        assert invalid.status_code == 502 and invalid.json() == {"detail": "ASR_UNAVAILABLE"}
        assert set(tmp_path.iterdir()) == existing
        assert fixture.receipt()["counts"]["audio_asr_requests"] == 4
        records = fixture.receipt()["audio"]["asr"]
        assert [row["case"] for row in records] == list(ASR_CASES)
        assert records[0]["wave"] == wave_facts(wave_bytes(1))
        assert records[1]["wave"]["pcmSha256"] == wave_facts(wave_bytes(2, 16000))["pcmSha256"]
        assert records[1]["wave"]["sampleRate"] == 16000
        assert len(events) == 2 and all(args == ("voice_transcribed",) for args, _ in events)
        assert all(item["properties"]["billing_status"] == "local_runtime"
                   and item["properties"]["actual_cost_usd"] == 0.0 for _, item in events)
        assert all(not ({"text", "audio", "transcript"} & item["properties"].keys()) for _, item in events)


def test_phone_tts_route_uses_real_http_validates_bytes_and_cleans_output(monkeypatch, tmp_path, capsys):
    existing = set(tmp_path.iterdir())
    with provider() as fixture:
        token = tmp_path / "speech-token"
        with token.open("x", encoding="ascii") as stream:
            stream.write(fixture.speech_token)
        token.chmod(0o600)
        monkeypatch.setenv("IZO_PHONE_TTS_PROVIDER", "http")
        monkeypatch.setenv("IZO_PHONE_TTS_HTTP_URL", fixture.base_url)
        monkeypatch.setenv("IZO_PHONE_TTS_HTTP_TOKEN_FILE", str(token))
        # The real urllib bridge explicitly ignores ambient proxies.
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
        monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
        def forbidden(*_args, **_kwargs):
            raise AssertionError("unexpected speech implementation")
        monkeypatch.setattr(phone_audio, "_synthesize_fake_speech", forbidden)
        monkeypatch.setattr(phone_audio, "_synthesize_windows_speech", forbidden)
        original_mkstemp = phone_audio.tempfile.mkstemp
        monkeypatch.setattr(phone_audio.tempfile, "mkstemp", lambda *args, **kwargs:
                            original_mkstemp(*args, **{**kwargs, "dir": tmp_path}))
        events, app = [], FastAPI()
        app.include_router(phone_audio.create_phone_audio_router(phone_audio.PhoneAudioDependencies(
            require_user=lambda _request: {"internal_user_id": "owned-audio-test"},
            record_event=lambda *args, **kwargs: events.append((args, kwargs)))))
        client = TestClient(app)
        for case, marker in (("irina", 5), ("pavel", 6), ("failure", None)):
            result = client.post("/api/phone/audio/speech", json=speech_request(case))
            if marker:
                assert result.status_code == 200
                assert result.headers["cache-control"] == "private, no-store"
                assert result.headers["content-type"].startswith("audio/wav")
                assert wave_facts(result.content) == wave_facts(wave_bytes(marker))
            else:
                assert result.status_code == 503
                assert result.json() == {"detail": "Озвучивание временно недоступно. Повторите позже."}
            assert set(tmp_path.iterdir()) == existing | {token}
        assert [row["case"] for row in fixture.receipt()["audio"]["speech"]] == ["irina", "pavel", "failure"]
        assert len(events) == 2
        assert all(item["properties"]["provider"] == "windows_speech_http" for _, item in events)
        output = capsys.readouterr()
        assert "D3_CANARY" not in output.out + output.err
        assert fixture.speech_token not in output.out + output.err
    token.unlink()
