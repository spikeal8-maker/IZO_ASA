"""Negative HTTP checks for the admitted offline fixture; no ASR/voice quality proof."""
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request

from tools.docker_shadow_product import ProductError, ProductFlow, require, validate_target

MAX_AUDIO = 8 * 1024 * 1024
CONFIG = "/api/phone/audio/config"
PLATFORM = "/api/phone/v1/platform"
LEDGER = "/api/account/token-history-v2"


def _admit(flow):
    require(isinstance(flow, ProductFlow) and bool(flow.saved), "FEATURE_LIVE_PRODUCT_FLOW_REQUIRED")
    origin = validate_target({"origin": flow.origin, "sourceSha": flow.source_sha, "project": flow.project,
        "isolatedData": True, "fakeProviderOnly": True, "networkEgressDenied": True, "externalEffectsDisabled": True})
    require(all(client.origin == origin for client in flow.clients), "FEATURE_CLIENT_TARGET_MISMATCH")


def _upload_status(client, duration, audio):
    require(audio is None or isinstance(audio, bytes) and len(audio) <= MAX_AUDIO + 1,
            "FEATURE_ASR_PROBE_TOO_LARGE")
    boundary = "izo-audio-validation"
    header = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="probe.invalid"\r\n'
              'Content-Type: application/octet-stream\r\n\r\n').encode("ascii")
    parts = [] if audio is None else [header, audio, b"\r\n"]
    body = b"".join([*parts, f"--{boundary}--\r\n".encode("ascii")])
    path = "/api/tools/transcribe?" + urlencode({"duration_ms": duration})
    request = Request(client.origin + path, data=body, method="POST", headers={"Origin": client.origin,
        "Content-Type": "multipart/form-data; boundary=" + boundary, "Accept": "application/json"})
    try:
        with client.opener.open(request, timeout=8) as response:
            status = response.status  # Never read success or error bodies for these negative cases.
    except HTTPError as error:
        status = error.code
        error.close()
    except (OSError, URLError, TimeoutError):
        raise ProductError("FEATURE_ASR_HTTP_UNAVAILABLE") from None
    require(type(status) is int and 100 <= status <= 599, "FEATURE_ASR_HTTP_STATUS_INVALID")
    return status


def _ledger(flow):
    value = flow.owner.request("GET", LEDGER)
    require(value.get("ok") is True and isinstance(value.get("summary"), dict)
            and isinstance(value.get("items"), list), "FEATURE_ASR_LEDGER_INVALID")
    return value["summary"], value["items"]


def asr_validation(flow, row):
    _admit(flow)
    config = flow.owner.request("GET", CONFIG)
    require(config.get("transcriptionPublished") is True and config.get("speechPublished") is True
            and type(config.get("transcriptionMaxBytes")) is int
            and config["transcriptionMaxBytes"] == MAX_AUDIO, "FEATURE_AUDIO_PROFILE_MISMATCH")
    row.update(evidenceScope="INSTALLED_HTTP_VALIDATION", transcriptionPublished=True, speechPublished=True,
               transcriptionMaxBytes=MAX_AUDIO, cases={}, successfulTranscription="NOT_VERIFIED",
               nonWavConversion="NOT_VERIFIED", providerErrorRedaction="NOT_VERIFIED")
    before = _ledger(flow)
    cases = (("guest", flow.guest, "10000", 1, 401), ("missing_file", flow.owner, "10000", None, 422),
             ("invalid_duration", flow.owner, "invalid", 1, 422), ("short", flow.owner, "0", 1, 400),
             ("empty", flow.owner, "10000", 0, 400), ("unsupported", flow.owner, "10000", 1, 415),
             ("at_limit_unsupported", flow.owner, "10000", MAX_AUDIO, 415),
             ("oversized", flow.owner, "10000", MAX_AUDIO + 1, 413))
    for name, client, duration, size, expected in cases:
        status = _upload_status(client, duration, None if size is None else b"x" * size)
        row["cases"][name] = status
        require(status == expected, "FEATURE_ASR_" + name.upper() + "_STATUS_INVALID")
    require(_ledger(flow) == before, "FEATURE_ASR_LEDGER_CHANGED")
    row.update(ownerLedger="UNCHANGED", negativeResponseBodies="NOT_READ")


def platform_capabilities(flow, row):
    from tools.docker_clean_features import public_fields

    _admit(flow)
    value = flow.owner.request("GET", PLATFORM)
    entries = value.get("workspaces")
    require(value.get("ok") is True and value.get("apiVersion") == "v1"
            and value.get("defaultRoute") == "/phone/image" and public_fields(value)
            and isinstance(entries, list) and len(entries) == 4
            and all(isinstance(item, dict) for item in entries), "FEATURE_PHONE_MANIFEST_INVALID")
    workspaces = {item.get("id"): item for item in entries}
    require(set(workspaces) == {"image", "video", "chat", "audio"}, "FEATURE_PHONE_WORKSPACES_MISMATCH")
    for identifier, item in workspaces.items():
        require(item.get("route") == "/phone/" + identifier and item.get("enabled") is True
                and item.get("stage") == ("partial" if identifier == "audio" else "ready")
                and item.get("navigation") == "primary", "FEATURE_PHONE_WORKSPACE_PROFILE_MISMATCH")
    require(workspaces["audio"].get("operations") == ["speech_to_text"], "FEATURE_PHONE_AUDIO_OPERATIONS_MISMATCH")
    flow.guest.request("GET", PLATFORM, expected=(401,))
    row.update(evidenceScope="INSTALLED_PHONE_MANIFEST", owner=200, guest=401,
               enabledWorkspaces=sorted(workspaces), audioStage="partial", audioOperations=["speech_to_text"],
               phoneThreeD="NOT_ADVERTISED", renderedUi="NOT_VERIFIED", threeDCreateApi="NOT_VERIFIED")
