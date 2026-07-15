from __future__ import annotations

import pytest
from fastapi import HTTPException

from tools.qwen_asr_service import _request_audio_and_language


def test_qwen_service_extracts_audio_and_forced_language():
    audio, language = _request_audio_and_language({
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "Transcribe the Russian speech exactly."},
                {"type": "audio_url", "audio_url": {"url": "data:audio/wav;base64,dGVzdA=="}},
            ],
        }],
    })

    assert audio == "data:audio/wav;base64,dGVzdA=="
    assert language == "Russian"


def test_qwen_service_rejects_request_without_audio():
    with pytest.raises(HTTPException) as exc:
        _request_audio_and_language({"messages": [{"role": "user", "content": []}]})
    assert exc.value.status_code == 400
