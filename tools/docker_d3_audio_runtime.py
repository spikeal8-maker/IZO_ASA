"""Actual API requests for an attested audio fixture; speech quality stays unverified.

Caller owns profile configuration, existing loopback listeners, token file and cleanup.
Its private receipt callback reads one fixed owned file <=64 KiB with an 8s bound;
the caller must enforce a 150s process deadline inside the fixture's 300s lifetime.
The HTTP client uses an 8s socket timeout; late results cannot establish PASS.
"""
from __future__ import annotations

import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request

from tools.docker_d3_audio_provider import (
    ASR_CASES, ASR_MODEL, MARKER, OGG, SPEECH_CASES, TRANSCRIPTS,
    digest, speech_request, wave_bytes, wave_facts,
)
from tools.docker_shadow_product import ProductError, ProductFlow, require, validate_target

ASR_PATH = "/api/tools/transcribe?duration_ms=1000&language=ru"
SPEECH_PATH = "/api/phone/audio/speech"
ASR_ERROR = "ASR_UNAVAILABLE"
SPEECH_ERROR = "Озвучивание временно недоступно. Повторите позже."
ROUTE_ASR_CASES = (*ASR_CASES, "invalid_ogg")


def admitted_audio(value):
    require(isinstance(value, dict) and value.get("fixture") == MARKER
            and value.get("lifetimeSeconds") == 300, "D3_AUDIO_PROFILE_REQUIRED")
    provider = value.get("provider", {})
    require(isinstance(provider, dict), "D3_AUDIO_PROVIDER_CONTRACT_INVALID")
    audio = provider.get("audio", {})
    require(isinstance(audio, dict) and provider.get("model_execution") is False and audio.get("profile") == MARKER
            and audio.get("lifetimeSeconds") == 300 and audio.get("modelExecution") is False
            and audio.get("acceleratorExecution") is False and audio.get("waveform") == "SYNTHETIC_TONE"
            and re.fullmatch(r"[a-f0-9]{32}", str(audio.get("instanceId", "")))
            and isinstance(audio.get("asr"), list) and len(audio["asr"]) <= 4
            and isinstance(audio.get("speech"), list) and len(audio["speech"]) <= 3,
            "D3_AUDIO_PROVIDER_CONTRACT_INVALID")
    return audio


def upload(case):
    require(case in ROUTE_ASR_CASES, "D3_AUDIO_CASE_INVALID")
    content = b"OggS-invalid-D3-sample" if case == "invalid_ogg" else OGG if case == "ogg" else wave_bytes(ASR_CASES.index(case) + 1)
    extension = "ogg" if case in {"ogg", "invalid_ogg"} else "wav"
    mime = "audio/" + extension
    boundary = "izo-d3-audio-protocol"
    header = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="d3-sample.{extension}"\r\n'
              f"Content-Type: {mime}\r\n\r\n").encode("ascii")
    body = header + content + f"\r\n--{boundary}--\r\n".encode("ascii")
    return body, "multipart/form-data; boundary=" + boundary, content


def exchange(client, path, body, mime, expected, deadline):
    require(path in {ASR_PATH, SPEECH_PATH} and isinstance(body, bytes) and 0 < len(body) <= 65536,
            "D3_AUDIO_REQUEST_INVALID")
    require(time.monotonic() < deadline, "D3_AUDIO_DEADLINE_EXCEEDED")
    request = Request(client.origin + path, data=body, method="POST", headers={
        "Origin": client.origin, "Content-Type": mime, "Accept": "application/json, audio/wav"})
    try:
        try:
            with client.opener.open(request, timeout=8) as response:
                status, headers, content = response.status, response.headers, response.read(65537)
        except HTTPError as error:
            status, headers = error.code, error.headers
            try:
                # Only these exact controlled errors may be read, validated and immediately discarded.
                content = error.read(2049) if status == expected and expected in {502, 503} else b""
            finally:
                error.close()
    except (OSError, URLError, TimeoutError):
        raise ProductError("D3_AUDIO_HTTP_UNAVAILABLE") from None
    require(time.monotonic() < deadline, "D3_AUDIO_DEADLINE_EXCEEDED")
    require(status == expected and len(content) <= (65536 if status == 200 else 2048),
            "D3_AUDIO_HTTP_RESPONSE_INVALID")
    if expected != 200:
        try:
            value = json.loads(content)
        except (ValueError, UnicodeError):
            raise ProductError("D3_AUDIO_ERROR_NOT_REDACTED") from None
        require(headers.get_content_type() == "application/json"
                and value == {"detail": ASR_ERROR if path == ASR_PATH else SPEECH_ERROR},
                "D3_AUDIO_ERROR_NOT_REDACTED")
        return None, headers
    return content, headers


def correlate(before, after, results):
    left, right = admitted_audio(before), admitted_audio(after)
    require(left["instanceId"] == right["instanceId"] and not left["asr"] and not left["speech"]
            and len(right["asr"]) == 4 and len(right["speech"]) == 3,
            "D3_AUDIO_PROVIDER_REPLAY_OR_CALL_MISMATCH")
    require(all(before["provider"].get(key) == after["provider"].get(key) for key in ("jobs", "uploads")),
            "D3_AUDIO_UNRELATED_PROVIDER_MUTATION")
    require(all(before["provider"].get("counts", {}).get(key, 0) == 0
                and type(after["provider"].get("counts", {}).get(key)) is int
                and after["provider"]["counts"][key] == count
                for key, count in (("audio_asr_requests", 4), ("audio_speech_requests", 3))),
            "D3_AUDIO_PROVIDER_ATTEMPT_COUNT_MISMATCH")
    for case, row in zip(ASR_CASES, right["asr"]):
        expected = wave_facts(wave_bytes(ASR_CASES.index(case) + 1, 16000 if case == "ogg" else 8000))
        facts = row.get("wave", {})
        require(row.get("case") == case and row.get("httpStatus") == (503 if case == "upstream_failure" else 200)
                and set(row) == {"case", "requestSha256", "httpStatus", "wave"}
                and re.fullmatch(r"[a-f0-9]{64}", str(row["requestSha256"]))
                and set(facts) == set(expected) and type(facts.get("bytes")) is int and 44 < facts["bytes"] <= 65536
                and re.fullmatch(r"[a-f0-9]{64}", str(facts.get("sha256", "")))
                and all(facts.get(key) == expected[key] for key in expected if key not in {"bytes", "sha256"}),
                "D3_AUDIO_ASR_PCM_OR_REQUEST_MISMATCH")
        require(case == "ogg" or facts == expected, "D3_AUDIO_WAV_PASSTHROUGH_MISMATCH")
    require(len({row["requestSha256"] for row in right["asr"]}) == 4, "D3_AUDIO_ASR_DUPLICATE_REQUEST")
    for (case, _rate), row in zip(SPEECH_CASES, right["speech"]):
        payload = speech_request(case)
        expected_wave = results["tts_" + case].get("wave")
        require(row == {"case": case, "requestSha256": digest(json.dumps(payload, ensure_ascii=False).encode()),
            "httpStatus": 503 if case == "failure" else 200, "voice": payload["voice"], "rate": payload["rate"],
            "textSha256": digest(payload["text"].encode()), "wave": expected_wave},
            "D3_AUDIO_TTS_HTTP_BRIDGE_MISMATCH")
    return {"status": "PASS", "instanceId": right["instanceId"], "asrRequests": 4, "speechRequests": 3,
            "wavPassthrough": True, "oggToPcm16k": True, "httpSpeechBridge": True}


def prove_audio_runtime(flow, *, attestation, provider_receipt, checkpoint=None):
    origin = validate_target(attestation)
    require(isinstance(flow, ProductFlow) and origin == flow.origin and origin.startswith("http://127.0.0.1:")
            and attestation["sourceSha"] == flow.source_sha and attestation["project"] == flow.project
            and all(client.origin == origin for client in flow.clients) and callable(provider_receipt),
            "D3_AUDIO_OWNED_FLOW_REQUIRED")
    report = {"status": "FAIL", "sourceSha": flow.source_sha, "project": flow.project,
        "evidenceScope": "INSTALLED_APPLICATION_CONTROLLED_AUDIO_PROTOCOL", "cases": {},
        "realSpeechRecognition": "NOT_VERIFIED", "realVoiceSynthesis": "NOT_VERIFIED",
        "audioUiResumeCancel": "NOT_RUN", "modelExecution": False, "acceleratorExecution": False}
    deadline = time.monotonic() + 120
    def record(name, value):
        report["cases"][name] = {"status": "PASS", "evidenceScope": "API_RESPONSE", **value}
        if checkpoint:
            checkpoint(report)
    try:
        before = provider_receipt()
        baseline = admitted_audio(before)
        require(not baseline["asr"] and not baseline["speech"], "D3_AUDIO_FRESH_PROFILE_REQUIRED")
        account = flow.account_snapshot(flow.owner)
        config = flow.owner.request("GET", "/api/phone/audio/config")
        require(config.get("speechPublished") is True and config.get("transcriptionPublished") is True,
                "D3_AUDIO_PUBLISHED_PROFILE_REQUIRED")
        for case in ROUTE_ASR_CASES:
            body, mime, source = upload(case)
            expected_status = 200 if case in TRANSCRIPTS else 502
            content, headers = exchange(flow.owner, ASR_PATH, body, mime, expected_status, deadline)
            if expected_status == 200:
                require(headers.get_content_type() == "application/json", "D3_AUDIO_ASR_CONTENT_TYPE_INVALID")
                value = json.loads(content)
                require(isinstance(value, dict) and value.get("ok") is True
                    and type(value.get("actualCostUsd")) in (int, float)
                    and isinstance(value.get("usage"), dict) and all(type(item) is int for item in value["usage"].values())
                    and value == {"ok": True, "text": TRANSCRIPTS[case], "model": ASR_MODEL, "provider": "qwen",
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0}, "actualCostUsd": 0.0},
                    "D3_AUDIO_ASR_RESULT_INVALID")
            record("asr_" + case, {"httpStatus": expected_status, "sourceBytes": len(source), "sourceSha256": digest(source)})
        for case, _rate in SPEECH_CASES:
            body = json.dumps(speech_request(case)).encode()
            expected_status = 503 if case == "failure" else 200
            content, headers = exchange(flow.owner, SPEECH_PATH, body, "application/json", expected_status, deadline)
            facts = None
            if expected_status == 200:
                require(headers.get_content_type() == "audio/wav" and headers.get("Cache-Control") == "private, no-store",
                        "D3_AUDIO_TTS_CACHE_OR_MIME_INVALID")
                facts = wave_facts(content)
                require(facts == wave_facts(wave_bytes(5 if case == "irina" else 6)), "D3_AUDIO_TTS_OUTPUT_MISMATCH")
            record("tts_" + case, {"httpStatus": expected_status, "wave": facts})
        receipt_deadline = min(deadline, time.monotonic() + 5)
        for _ in range(26):
            require(time.monotonic() < receipt_deadline, "D3_AUDIO_RECEIPT_TIMEOUT")
            after = provider_receipt()
            require(time.monotonic() < receipt_deadline, "D3_AUDIO_RECEIPT_TIMEOUT")
            current = admitted_audio(after)
            if len(current["asr"]) == 4 and len(current["speech"]) == 3:
                break
            time.sleep(.2)
        report["provider"] = correlate(before, after, report["cases"])
        require(flow.account_snapshot(flow.owner) == account, "D3_AUDIO_ACCOUNT_OR_LEDGER_CHANGED")
        require(time.monotonic() < deadline, "D3_AUDIO_DEADLINE_EXCEEDED")
        report.update(status="PASS", ownerAccountAndLedger="UNCHANGED")
    except Exception as error:
        code = str(error)
        report["errorCode"] = code if isinstance(error, ProductError) and re.fullmatch(r"D3_[A-Z0-9_]{2,100}", code) else "D3_AUDIO_RUNTIME_FAILED"
    if checkpoint:
        checkpoint(report)
    return report
