from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.routers import phone_audio
from backend.app.api.routers.phone_audio import PhoneAudioDependencies, create_phone_audio_router


def test_phone_speech_returns_wave_and_authenticates(monkeypatch):
    seen = {"auth": False}

    def require_user(_request):
        seen["auth"] = True
        return {"id": "web-test"}

    def synthesize(text, voice, rate, output_path):
        assert text == "Привет"
        assert voice == "pavel"
        assert rate == 2
        Path(output_path).write_bytes(b"RIFFtestWAVE")

    monkeypatch.setattr(phone_audio, "_synthesize_windows_speech", synthesize)
    app = FastAPI()
    app.include_router(create_phone_audio_router(PhoneAudioDependencies(require_user)))

    response = TestClient(app).post(
        "/api/phone/audio/speech",
        json={"text": "Привет", "voice": "pavel", "rate": 2},
    )

    assert seen["auth"] is True
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content == b"RIFFtestWAVE"


def test_phone_speech_rejects_blank_text():
    app = FastAPI()
    app.include_router(create_phone_audio_router(PhoneAudioDependencies(lambda _request: {"id": "web-test"})))

    response = TestClient(app).post("/api/phone/audio/speech", json={"text": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == "Введите текст для озвучивания."
