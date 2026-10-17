"""Bounded D3 API checks on a caller-admitted, live Docker ProductFlow fixture."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.request import Request
import uuid
import wave

from tools.docker_shadow_product import ProductError, ProductFlow, path_id, validate_target

THREADS = "/api/phone/chat/threads"
SPEECH = "/api/phone/audio/speech"


class FeatureError(RuntimeError):
    pass


def require(value, code):
    if not value:
        raise FeatureError(code)


def error_code(error):
    value = str(error)
    trusted = isinstance(error, (FeatureError, ProductError))
    return value if trusted and re.fullmatch(r"(?:FEATURE|PRODUCT)_[A-Z0-9_]{2,100}", value) else "FEATURE_OPERATION_FAILED"


def health(flow, row):
    value = flow.guest.request("GET", "/api/health")
    row.update(httpStatus=200, ok=value.get("ok") is True, ready=value.get("ready") is True)
    require(row["ok"] and row["ready"], "FEATURE_DATABASE_NOT_READY")


def chat_history(flow, row):
    title, thread_id, complete = "Docker D3 " + uuid.uuid4().hex, None, False
    before = flow.owner.request("GET", THREADS)
    require(before.get("ok") is True and isinstance(before.get("threads"), list), "FEATURE_CHAT_LIST_INVALID")
    known = {item["id"] for item in before["threads"]}
    try:
        created = flow.owner.request("POST", THREADS, {
            "title": title, "chatModelId": "local:izo-chat", "contextChars": 4000})
        identifier = path_id(created["thread"]["id"])
        require(identifier not in known, "FEATURE_CHAT_CREATE_REUSED_THREAD")
        thread_id = identifier
        require(created.get("ok") is True and created["thread"].get("title") == title,
                "FEATURE_CHAT_CREATE_INVALID")
        path = THREADS + "/" + thread_id
        listed = flow.owner.request("GET", THREADS)
        require(any(item["id"] == thread_id for item in listed["threads"]), "FEATURE_CHAT_NOT_LISTED")
        changed = flow.owner.request("PATCH", path, {"title": title + " edited"})
        require(changed.get("ok") is True and changed["thread"].get("id") == thread_id
                and changed["thread"].get("title") == title + " edited", "FEATURE_CHAT_UPDATE_INVALID")
        messages = flow.owner.request("GET", path + "/messages")
        require(messages.get("ok") is True and messages["thread"]["id"] == thread_id
                and messages["thread"].get("title") == title + " edited"
                and messages.get("messages") == [], "FEATURE_CHAT_READ_INVALID")
        require(all(item["id"] != thread_id for item in flow.other.request("GET", THREADS)["threads"]),
                "FEATURE_CHAT_OTHER_LIST_LEAK")
        for method, suffix, payload in (("GET", "/messages", None), ("PATCH", "", {"title": "denied"}),
                                         ("DELETE", "", None)):
            flow.other.request(method, path + suffix, payload, expected=(404,))
            flow.guest.request(method, path + suffix, payload, expected=(401,))
        flow.guest.request("GET", THREADS, expected=(401,))
        flow.guest.request("POST", THREADS, {"title": "denied"}, expected=(401,))
        complete = True
        row.update(ownedCrud="PASS", otherUser="404", guest="401", inference="NOT_RUN")
    except Exception as error:
        row["errorCode"] = error_code(error)
        raise
    finally:
        try:
            if thread_id is None:
                after = flow.owner.request("GET", THREADS)
                require(after.get("ok") is True and isinstance(after.get("threads"), list),
                        "FEATURE_CHAT_CLEANUP_LIST_INVALID")
                matches = [item for item in after["threads"]
                           if item.get("id") not in known and item.get("title") == title]
                require(len(matches) <= 1, "FEATURE_CHAT_CLEANUP_AMBIGUOUS")
                thread_id = path_id(matches[0]["id"]) if matches else None
            if thread_id is not None:
                removed = flow.owner.request("DELETE", THREADS + "/" + thread_id, expected=(200, 404))
                flow.owner.request("GET", THREADS + "/" + thread_id + "/messages", expected=(404,))
                require(not complete or removed.get("ok") is True, "FEATURE_CHAT_DELETE_INVALID")
            row["threadCleanup"] = "PASS" if thread_id is not None else "NO_MATCHING_THREAD"
        except Exception as error:
            row["threadCleanup"], row["cleanupError"] = "FAIL", error_code(error)
            raise FeatureError("FEATURE_CHAT_CLEANUP_FAILED") from None


def fake_speech(flow, row):
    config = flow.owner.request("GET", "/api/phone/audio/config")
    require(config.get("speechPublished") is True and config.get("speechMaxChars") == 4000
            and {voice["id"] for voice in config.get("voices", [])} >= {"irina", "pavel"},
            "FEATURE_SPEECH_CONFIG_INVALID")
    body = {"text": "Docker fixture voice", "voice": "irina", "rate": 0}
    flow.guest.request("GET", "/api/phone/audio/config", expected=(401,))
    flow.guest.request("POST", SPEECH, body, expected=(401,))
    request = Request(flow.origin + SPEECH, data=json.dumps(body).encode(), method="POST",
                      headers={"Origin": flow.origin, "Content-Type": "application/json", "Accept": "audio/wav"})
    try:
        with flow.owner.opener.open(request, timeout=8) as response:
            require(response.status == 200, "FEATURE_SPEECH_HTTP_INVALID")
            content_type, cache = response.headers.get_content_type(), response.headers.get("Cache-Control", "")
            content = response.read(2000001)
    except HTTPError as error:
        code = error.code
        error.close()
        raise FeatureError(f"FEATURE_SPEECH_HTTP_{code}") from None
    require(len(content) <= 2000000 and content_type == "audio/wav"
            and {part.strip().lower() for part in cache.split(",")} >= {"private", "no-store"},
            "FEATURE_SPEECH_RESPONSE_INVALID")
    with wave.open(io.BytesIO(content), "rb") as audio:
        require((audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getnframes())
                == (1, 2, 8000, 800) and audio.readframes(800) == b"\0\0" * 800,
                "FEATURE_FAKE_SPEECH_WAV_INVALID")
    row.update(httpStatus=200, bytes=len(content), sha256=hashlib.sha256(content).hexdigest(),
               cacheControl="private, no-store", fixture="SILENT_PCM_8KHZ_MONO_16BIT_800_FRAMES",
               realSpeech="NOT_VERIFIED", guest="401")


def commerce(flow, row):
    value = flow.guest.request("GET", "/api/public/commerce-v2")
    require(value.get("ok") is True and value.get("payments_available") is False
            and "payment_provider" in value and value["payment_provider"] is None,
            "FEATURE_COMMERCE_NOT_DISABLED")
    row.update(paymentsAvailable=False, paymentProvider=None, livePayments="NOT_VERIFIED")


def admin_boundary(flow, row):
    path = "/api/admin/runtime-health-v2"
    flow.owner.request("GET", path, expected=(403,))
    flow.guest.request("GET", path, expected=(401,))
    row.update(ordinaryUser="403", guest="401", privilegedActions="NOT_RUN")


def bot_webhooks(flow, row):
    for provider in ("telegram", "max"):
        flow.guest.request("POST", f"/api/{provider}/webhook", {}, expected=(404,))
        row[provider] = {"disabledWebhookHttpStatus": 404, "liveIntegration": "NOT_VERIFIED"}


def video_config(flow, row):
    value = flow.owner.request("GET", "/api/video/config", expected=(200, 500))
    row["httpStatus"] = value.get("httpStatus", 200)
    require(row["httpStatus"] == 200, "FEATURE_VIDEO_CONFIG_HTTP_500")
    require(isinstance(value.get("modes"), dict) and isinstance(value.get("availability"), dict),
            "FEATURE_VIDEO_CONFIG_INVALID")
    row.update(config="PASS", modelExecution="NOT_VERIFIED")


def prove_features(flow: ProductFlow, receipt: Path) -> dict:
    """Caller performs D1/D2 source comparisons first and later removes its fixture."""
    require(isinstance(flow, ProductFlow) and bool(flow.saved), "FEATURE_LIVE_PRODUCT_FLOW_REQUIRED")
    origin = validate_target({"origin": flow.origin, "sourceSha": flow.source_sha, "project": flow.project,
        "isolatedData": True, "fakeProviderOnly": True, "networkEgressDenied": True, "externalEffectsDisabled": True})
    require(all(client.origin == origin for client in flow.clients), "FEATURE_CLIENT_TARGET_MISMATCH")
    report = {"status": "FAIL", "sourceSha": flow.source_sha, "project": flow.project, "origin": origin,
              "startedAt": datetime.now(timezone.utc).isoformat(), "checks": {}}
    receipt = Path(receipt)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with receipt.open("x", encoding="utf-8") as output:
        receipt.chmod(0o600)
        for name, action in (("health", health), ("chatHistory", chat_history), ("fakeSpeech", fake_speech),
                             ("commerceDisabled", commerce), ("adminBoundary", admin_boundary),
                             ("botWebhookDisabled", bot_webhooks), ("videoConfig", video_config)):
            row = report["checks"][name] = {"status": "FAIL"}
            try:
                action(flow, row)
                row["status"] = "PASS"
            except Exception as error:
                row.setdefault("errorCode", error_code(error))
        report["checks"]["chatInference"] = {"status": "BLOCKED", "execution": "NOT_RUN",
            "reasonCode": "FIXTURE_OLLAMA_ENDPOINT_UNAVAILABLE", "configuredEndpoint": "http://127.0.0.1:1",
            "configurationSource": "ops/docker/dev/compose.yml", "featureDisabled": False}
        report["checks"]["threeD"] = {"status": "NOT_VERIFIED", "evidence": "SOURCE_CONTRACT_ONLY",
                                      "durableApi": "NOT_VERIFIED"}
        report["status"] = "FAIL" if any(row["status"] == "FAIL" for row in report["checks"].values()) else "PARTIAL"
        report["finishedAt"] = datetime.now(timezone.utc).isoformat()
        json.dump(report, output, indent=2)
        output.write("\n")
    return report
