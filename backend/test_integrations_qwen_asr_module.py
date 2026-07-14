import asyncio
import json

import httpx

from backend.app.integrations.qwen_asr import fetch_qwen_asr_status, request_qwen_asr_transcription


def test_fetch_qwen_asr_status_reports_models():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "Qwen/Qwen3-ASR-1.7B"}]})

    result = asyncio.run(fetch_qwen_asr_status(base_url="http://asr", transport=httpx.MockTransport(handler)))
    assert result["ok"] is True
    assert result["models"][0]["id"] == "Qwen/Qwen3-ASR-1.7B"


def test_request_qwen_asr_transcription_sends_audio_url():
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        audio_url = body["messages"][0]["content"][1]["audio_url"]["url"]
        assert audio_url.startswith("data:audio/wav;base64,")
        assert body["model"] == "Qwen/Qwen3-ASR-1.7B"
        return httpx.Response(200, json={"choices": [{"message": {"content": "тест записи"}}]})

    text, _ = asyncio.run(request_qwen_asr_transcription(
        audio=b"RIFF-audio",
        audio_format="wav",
        language="Russian",
        base_url="http://asr",
        transport=httpx.MockTransport(handler),
    ))
    assert text == "тест записи"


def test_request_qwen_asr_transcription_rejects_empty_result():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})

    try:
        asyncio.run(request_qwen_asr_transcription(
            audio=b"audio",
            audio_format="wav",
            language="Russian",
            base_url="http://asr",
            transport=httpx.MockTransport(handler),
        ))
    except RuntimeError as exc:
        assert "не распознал" in str(exc)
    else:
        raise AssertionError("RuntimeError was not raised")
