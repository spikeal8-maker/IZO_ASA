from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.routers import phone_audio
from backend.app.api.routers.phone_audio import PhoneAudioDependencies, create_phone_audio_router


def _phone_app(*, record_event=None, audio_config=None) -> FastAPI:
    app = FastAPI()
    app.include_router(create_phone_audio_router(PhoneAudioDependencies(
        require_user=lambda _request: {"id": "web-test", "internal_user_id": "internal-test"},
        audio_config=audio_config,
        record_event=record_event,
    )))
    return app


def test_phone_speech_returns_wave_and_authenticates(monkeypatch):
    seen = {"auth": False}
    events = []

    def require_user(_request):
        seen["auth"] = True
        return {"id": "web-test", "internal_user_id": "internal-test"}

    monkeypatch.setenv("IZO_PHONE_TTS_PROVIDER", "fake")
    app = FastAPI()
    app.include_router(create_phone_audio_router(PhoneAudioDependencies(
        require_user=require_user,
        record_event=lambda *args, **kwargs: events.append((args, kwargs)),
    )))

    response = TestClient(app).post(
        "/api/phone/audio/speech",
        json={"text": "Привет", "voice": "pavel", "rate": 2},
    )

    assert seen["auth"] is True
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content[:4] == b"RIFF"
    assert response.content[8:12] == b"WAVE"
    assert len(response.content) == 1644
    assert events[0][1]["properties"]["provider"] == "fake_speech"


def test_fake_speech_provider_is_deterministic_bounded_wave(tmp_path):
    provider = phone_audio.resolve_phone_speech_provider(
        {"IZO_PHONE_TTS_PROVIDER": "fake"},
        platform_name="posix",
    )
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"

    provider.synthesize("Привет", "irina", 0, str(first))
    provider.synthesize("Другой текст", "pavel", 5, str(second))

    assert provider.event_name == "fake_speech"
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes()[:4] == b"RIFF"
    assert first.read_bytes()[8:12] == b"WAVE"
    assert 44 < first.stat().st_size <= 2048


def test_windows_default_provider_preserves_system_speech_command(monkeypatch, tmp_path):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["env"] = kwargs["env"]
        Path(kwargs["env"]["IZO_TTS_OUTPUT"]).write_bytes(b"RIFFtestWAVE")
        return phone_audio.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(phone_audio.subprocess, "run", fake_run)
    provider = phone_audio.resolve_phone_speech_provider({}, platform_name="nt")
    output = tmp_path / "windows.wav"
    provider.synthesize("Привет", "irina", 1, str(output))

    assert provider.event_name == "windows_speech"
    assert seen["command"][:4] == ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"]
    assert "System.Speech" in seen["command"][4]
    assert seen["env"]["IZO_TTS_VOICE"] == "Microsoft Irina Desktop"
    assert seen["env"]["IZO_TTS_RATE"] == "1"
    assert output.is_file()


def test_phone_speech_non_windows_unconfigured_fails_closed(monkeypatch):
    original_resolver = phone_audio.resolve_phone_speech_provider
    monkeypatch.delenv("IZO_PHONE_TTS_PROVIDER", raising=False)
    monkeypatch.setattr(
        phone_audio,
        "resolve_phone_speech_provider",
        lambda: original_resolver({}, platform_name="posix"),
    )

    response = TestClient(_phone_app()).post(
        "/api/phone/audio/speech",
        json={"text": "Привет"},
    )

    assert response.status_code == 503


def test_phone_speech_unknown_provider_fails_closed(monkeypatch):
    monkeypatch.setenv("IZO_PHONE_TTS_PROVIDER", "garbage")

    response = TestClient(_phone_app()).post(
        "/api/phone/audio/speech",
        json={"text": "Привет"},
    )

    assert response.status_code == 503


def test_phone_speech_rejects_blank_text():
    response = TestClient(_phone_app()).post(
        "/api/phone/audio/speech",
        json={"text": "   "},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Введите текст для озвучивания."


def test_phone_audio_publication_contract_is_server_enforced():
    app = _phone_app(audio_config=lambda: {
        "transcriptionPublished": True,
        "speechPublished": False,
    })
    client = TestClient(app)

    config = client.get("/api/phone/audio/config")
    speech = client.post("/api/phone/audio/speech", json={"text": "Привет"})

    assert config.status_code == 200
    assert config.json()["speechPublished"] is False
    assert {item["id"] for item in config.json()["voices"]} == {"irina", "pavel"}
    assert speech.status_code == 403
