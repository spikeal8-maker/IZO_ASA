"""Run the bounded D3 browser on a caller-owned, already attested Docker profile."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

from tools.docker_shadow import HOST_ENV
from tools.docker_shadow_product import ProductError, ProductFlow, path_id, require, validate_target

MARKER = "controlled-chat-video-v1"
ROOT = Path(__file__).resolve().parents[1]
PHONE_HELPER_SHA256 = "64e739f3b2220a846c89fef81a8ea7744c735f99f9bfd56270a8dc2745c3a1b0"


def admitted_provider(value):
    require(isinstance(value, dict) and value.get("fixture") == MARKER
            and value.get("lifetimeSeconds") == 300
            and re.fullmatch(r"[a-f0-9]{32}", str(value.get("instanceId", ""))), "D3_PROVIDER_PROFILE_REQUIRED")
    provider = value.get("provider", {})
    d3 = provider.get("d3", {})
    require(provider.get("model_execution") is False and d3.get("profile") == MARKER
            and d3.get("modelExecution") is False and d3.get("acceleratorExecution") is False
            and isinstance(d3.get("chat"), list) and len(d3["chat"]) <= 8
            and isinstance(provider.get("jobs"), list) and len(provider["jobs"]) <= 64,
            "D3_PROVIDER_CONTRACT_INVALID")
    return provider


def correlate(before, after, browser, *, phone_watch=None):
    left, right = admitted_provider(before), admitted_provider(after)
    require(before["instanceId"] == after["instanceId"] and not left["d3"]["chat"]
            and left["d3"]["video"] is None, "D3_PROVIDER_BASELINE_CHANGED")
    chat = right["d3"]["chat"]
    require(len(chat) == 5 and [item["stage"] for item in chat] == ["first", "second", "failed", "image", "done"]
            and all(item["runId"] == browser["runId"] for item in chat)
            and [item["httpStatus"] for item in chat] == [200, 200, 502, 200, 200]
            and chat[1]["historyConfirmed"] is True and chat[-1]["toolRound"] is True,
            "D3_CHAT_PROVIDER_REPLAY_OR_HISTORY_MISMATCH")
    for provider in (left, right):
        jobs = provider["jobs"]
        require(all(isinstance(item, dict) for item in jobs), "D3_PROVIDER_JOBS_INVALID")
        for field, pattern in (("prompt_id", r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}"),
                               ("client_sha256", r"[a-f0-9]{64}"), ("body_sha256", r"[a-f0-9]{64}")):
            values = [item.get(field) for item in jobs]
            require(all(isinstance(value, str) and re.fullmatch(pattern, value) for value in values)
                    and len(set(values)) == len(values), "D3_PROVIDER_REPLAY_OR_DIGEST_INVALID")
        accepted = provider.get("counts", {}).get("accepted", 0)
        require(type(accepted) is int and accepted == len(jobs), "D3_PROVIDER_COUNT_INVALID")
    previous = {item["prompt_id"]: item for item in left["jobs"]}
    current = {item["prompt_id"]: item for item in right["jobs"]}
    require(previous.keys() <= current.keys() and all(current[key] == item for key, item in previous.items()),
            "D3_PROVIDER_BASELINE_CHANGED")
    images = [item for key, item in current.items() if key not in previous]
    expected_client = hashlib.sha256(("onenode-backend-" + browser["image"]["jobId"]).encode()).hexdigest()
    if phone_watch is not None:
        accepted_phone_watch(phone_watch, browser)
    require(len(images) == 1 and images[0]["state"] == "completed"
            and images[0].get("mode") == ("hold" if phone_watch is not None else "complete")
            and images[0]["client_sha256"] == expected_client
            and right["counts"].get("accepted", 0) - left["counts"].get("accepted", 0) == 1,
            "D3_IMAGE_PROVIDER_SUBMIT_MISMATCH")
    if phone_watch is not None:
        require(phone_watch["providerInstanceId"] == after["instanceId"]
                and phone_watch["promptId"] == images[0]["prompt_id"], "D3_PHONE_PROVIDER_CHANGED")
    video, observed = right["d3"]["video"], browser["checks"]["video"]
    require(isinstance(video, dict) and video["jobId"] == observed["jobId"]
            and video["statusReads"] >= 2 and video["downloads"] == 1
            and (video["width"], video["height"], video["frames"], video["frameRate"]) == (832, 480, 25, 12)
            and right["d3"]["clipSha256"] == observed["sha256"]
            and right["d3"]["clipBytes"] == observed["bytes"], "D3_LTX_PROVIDER_MEDIA_MISMATCH")
    return {"status": "PASS", "providerInstanceId": after["instanceId"], "chatCalls": chat,
            "imageSubmit": images[0], "ltxSubmit": video,
            "imageExecutionBoundary": "leased worker", "videoExecutionBoundary": "existing API LTX adapter",
            "modelExecution": False, "acceleratorExecution": False}


def receipt(directory, name):
    path = directory / name
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 65536,
            "D3_BROWSER_RECEIPT_MISSING")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), "D3_BROWSER_RECEIPT_INVALID")
    return value


def owned_image(value, source_sha, project):
    require(value.get("sourceSha") == source_sha and value.get("project") == project
            and re.fullmatch(r"[a-f0-9]{32}", str(value.get("runId", ""))), "D3_BROWSER_IDENTITY_MISMATCH")
    image = value.get("image")
    require(isinstance(image, dict) and set(image) == {"id", "url", "jobId", "tokenCost"}
            and all(isinstance(image.get(key), str) and re.fullmatch(r"[A-Za-z0-9_-]{1,120}", image[key])
                    for key in ("id", "jobId")) and type(image.get("tokenCost")) is int and image["tokenCost"] > 0
            and isinstance(image.get("url"), str) and re.fullmatch(
                r"/api/media/[A-Za-z0-9_-][A-Za-z0-9_.-]{0,219}(?:\?userId=web_[0-9a-f]{32})?", image["url"]),
            "D3_BROWSER_IMAGE_INVALID")
    return image


def clean_process(value, returncode):
    cleanup = value.get("cleanup", {})
    require(type(returncode) is int and returncode == 0 and value.get("status") == "PASS" and value.get("timedOut") is False
            and value.get("scope") == "PRIVATE_LINUX_SUBREAPER" and type(value.get("nodeReturncode")) is int
            and value["nodeReturncode"] == 0 and isinstance(cleanup, dict) and cleanup.get("status") == "PASS"
            and all(type(cleanup.get(key)) is int and cleanup[key] == 0
                    for key in ("childrenAtShutdown", "remainingChildren"))
            and "errorCode" not in value, "D3_BROWSER_PROCESS_NOT_CLEAN")


def accepted_accounting(accounting, cost, chat_entries):
    require(type(cost) is int and cost > 0 and isinstance(accounting, dict)
            and accounting.get("status") == "PASS" and type(accounting.get("tokenCost")) is int
            and accounting["tokenCost"] == cost
            and all(type(accounting.get(key)) is int and accounting[key] >= 0
                    for key in ("mainBalanceDebit", "dailyBudgetDebit", "refundDelta", "zeroTokenChatEntries"))
            and accounting["mainBalanceDebit"] + accounting["dailyBudgetDebit"] == cost
            and accounting["refundDelta"] == 0 and accounting["zeroTokenChatEntries"] == chat_entries,
            "D3_BROWSER_ACCOUNTING_INCOMPLETE")


def accepted_browser(browser):
    """A top-level PASS cannot replace any required scenario or its accounting proof."""
    require(browser.get("status") == "PASS" and browser.get("sessionCleanup") == "PASS"
            and browser.get("browserCleanup") == "PASS" and "errorCode" not in browser,
            "D3_BROWSER_FAILED")
    checks = browser.get("checks")
    require(isinstance(checks, dict) and set(checks) == {"chat", "chatImage", "phone3d", "desktop3d", "video"}
            and all(isinstance(case, dict) and case.get("status") == "PASS" and "errorCode" not in case
                    for case in checks.values()), "D3_BROWSER_CHECKS_INCOMPLETE")
    image = browser.get("image", {})
    for name, cost in (("chatImage", image.get("tokenCost")), ("video", checks["video"].get("tokenCost"))):
        accepted_accounting(checks[name].get("accounting"), cost, 1 if name == "chatImage" else 0)


def accepted_phone_watch(watch, browser):
    """A held provider is accepted only with the joined private watcher and actual helper result."""
    phone = browser.get("checks", {}).get("chatImage", {}).get("phoneActive", {})
    image = browser.get("image", {})
    job_id, decoded, observations = image.get("jobId"), phone.get("decoded", {}), phone.get("observations", {})
    require(isinstance(watch, dict) and watch.get("status") == "PASS" and "errorCode" not in watch
            and watch.get("cleanup") == "PASS" and watch.get("threadAlive") is False
            and watch.get("fullJobOwnerVerified") is True and watch.get("wasHeld") is True
            and type(watch.get("newGenerationRequests")) is int and watch["newGenerationRequests"] == 0
            and type(watch.get("releaseSeconds")) in {int, float} and 0 <= watch["releaseSeconds"] < 55
            and isinstance(job_id, str) and watch.get("jobId") == phone.get("jobId") == job_id
            and watch.get("clientSha256") == hashlib.sha256(("onenode-backend-" + job_id).encode()).hexdigest()
            and phone.get("status") == "PASS" and phone.get("uiCancellation") == "NOT_SUPPORTED"
            and "errorCode" not in phone and phone.get("imageId") == image.get("id")
            and phone.get("imageUrl") == decoded.get("url") == image.get("url") and decoded.get("complete") is True
            and all(type(decoded.get(key)) is int and 0 < decoded[key] <= 8192 for key in ("width", "height"))
            and phone.get("statuses", {}).keys() == {"initialStatus", "reloadedStatus", "returnedStatus"}
            and all(value in {"queued", "running", "processing"} for value in phone["statuses"].values())
            and all(observations.get(key) is True for key in ("sameJobAfterReload", "spaSignalAborted"))
            and all(type(observations.get(key)) is int and observations[key] == 0
                    for key in ("pollsAfterUnmount", "imageSubmits", "videoSubmits"))
            and type(phone.get("newGenerationRequests")) is int and phone["newGenerationRequests"] == 0
            and all(watch.get(key) == phone.get(key) == browser.get(key) for key in ("sourceSha", "project", "runId"))
            and watch.get("holdAck") == {"sequence": 1, "action": "hold", "status": "ACK"}
            and watch.get("releaseAck") == {"sequence": 2, "action": "release", "status": "ACK"},
            "D3_PHONE_RELEASE_NOT_PROVEN")


def _publication_digest(value):
    encoded = json.dumps(value, sort_keys=True, allow_nan=False).encode()
    require(len(encoded) <= 65536, "D3_FEED_METADATA_LIMIT")
    return hashlib.sha256(encoded).hexdigest()


def _publication_snapshot(flow, observed):
    job_id, gallery_id, pub_id = (observed[key] for key in ("jobId", "galleryId", "publicationId"))
    private, public = f"/api/video/media/{job_id}", f"/api/feed/video/{pub_id}?variant=full"
    identities = {}
    for name, client in (("owner", flow.owner), ("other", flow.other)):
        me = client.request("GET", "/api/me-v2")
        identities[name] = {key: me.get(key) for key in ("legacy_user_id", "internal_user_id")}
        require(identities[name] == {key: flow.saved["accounts"][name]["identity"][key]
                for key in identities[name]}, "D3_FEED_OWNER_CHANGED")
    require(identities["owner"] != identities["other"], "D3_FEED_FOREIGN_PRINCIPAL_REQUIRED")
    flow.guest.request("GET", "/api/me-v2", expected=(401,))
    job = flow.owner.request("GET", f"/api/video/jobs/{job_id}")
    phone = flow.owner.request("GET", f"/api/phone/v1/jobs/{job_id}")
    phone_job = phone.get("job", {})
    require(all(row.get("id") == job_id and row.get("status") == "completed" for row in (job, phone_job))
            and job.get("videoUrl") == private
            and job.get("galleryVideoId") == gallery_id and job.get("galleryDeleted") is False
            and phone.get("ok") is True and phone_job.get("terminal") is True
            and phone_job.get("result", {}).get("id") == gallery_id
            and phone_job["result"].get("url") == private, "D3_FEED_JOB_CHANGED")
    publication = flow.owner.request("GET", f"/api/feed/publications/{pub_id}/status")
    require(publication.get("ok") is True, "D3_FEED_NOT_READY")
    owner = publication.get("publication", {})
    feed = flow.guest.request("GET", "/api/feed?type=fresh&limit=60")
    gallery = flow.owner.request("GET", "/api/gallery/items?limit=60&filter=video")
    selected = []
    for envelope, wanted in ((feed, pub_id), (gallery, gallery_id)):
        items = envelope.get("items")
        require(isinstance(items, list) and len(items) <= 60 and all(isinstance(v, dict) for v in items),
                "D3_FEED_LIST_INVALID")
        matches = [v for v in items if v.get("id") == wanted]
        require(len(matches) == 1, "D3_FEED_RESULT_MISSING")
        selected.append(matches[0])
    guest, item = selected
    expected = {"id": pub_id, "video_id": gallery_id, "image_id": None, "media_type": "video",
        "status": "published", "media_status": "ready", "moderation_status": "approved",
        "user_id": identities["owner"]["internal_user_id"], "video_url": public}
    require(all(not row.get("media_error") and all(row.get(k) == v for k, v in expected.items())
                for row in (owner, guest)), "D3_FEED_NOT_READY")
    require(item.get("mediaType") == "video" and item.get("videoUrl") == private
            and item.get("publicationId") == pub_id and item.get("published") is True
            and (item.get("width"), item.get("height")) == (832, 480), "D3_FEED_GALLERY_CHANGED")
    for client, denied in ((flow.other, 404), (flow.guest, 401)):
        for route in (f"/api/video/jobs/{job_id}", f"/api/phone/v1/jobs/{job_id}",
                      f"/api/feed/publications/{pub_id}/status", private):
            client.request("GET", route, expected=(denied,))
    media = {}
    for name, client, route, sha_key, bytes_key in (("private", flow.owner, private, "sha256", "bytes"),
            ("public", flow.guest, public, "publicSha256", "publicBytes")):
        body = client.request("GET", route, binary=True)
        require(isinstance(body, bytes) and len(body) == observed[bytes_key] and body[4:8] == b"ftyp"
                and hashlib.sha256(body).hexdigest() == observed[sha_key], "D3_FEED_MEDIA_CHANGED")
        media[name] = {"sha256": observed[sha_key], "bytes": len(body)}
    records = {"owner": identities, "job": job, "phone": phone, "gallery": item,
               "ownerPublication": owner, "guestPublication": guest}
    return {"metadataSha256": {key: _publication_digest(value) for key, value in records.items()}, "media": media}


def prove_publication_restart(flow, attestation, video, recreate, read_identity, image_id):
    """Existing 90 s step, 20 MB HTTP cap, 8 s socket timeout; metadata cap after parsing."""
    require(isinstance(flow, ProductFlow) and validate_target(attestation) == flow.origin
            and flow.source_sha == attestation["sourceSha"] and flow.project == attestation["project"]
            and all(client.origin == flow.origin for client in flow.clients), "D3_OWNED_FLOW_REQUIRED")
    browser = video.get("browser", {})
    owned_image(browser, flow.source_sha, flow.project)
    accepted_browser(browser)
    clean_process(video.get("process", {}), 0)
    require(video.get("status") == "PASS" and "errorCode" not in video
            and all(video.get(key) == browser.get(key) for key in ("sourceSha", "project", "runId"))
            and browser.get("modelExecution") is False and browser.get("acceleratorExecution") is False,
            "D3_FEED_BROWSER_NOT_ACCEPTED")
    observed = browser["checks"]["video"]
    for key in ("jobId", "galleryId", "publicationId"):
        path_id(observed.get(key))
    require(all(isinstance(observed.get(key), str) and re.fullmatch(r"[a-f0-9]{64}", observed[key])
                    for key in ("sha256", "publicSha256"))
            and all(type(observed.get(key)) is int and 1024 < observed[key] <= maximum
                    for key, maximum in (("bytes", 1048576), ("publicBytes", 2097152)))
            and observed.get("publicMediaProof") == "GUEST_FETCH_AND_DECODE"
            and observed.get("metadataMatches") is True
            and all((observed.get(key, {}).get("width"), observed.get(key, {}).get("height")) == (832, 480)
                    and type(observed[key].get("duration")) in {int, float} and 2 < observed[key]["duration"] < 2.2
                    for key in ("playback", "publicPlayback")), "D3_FEED_DECODE_NOT_PROVEN")
    def capture():
        identity = read_identity()
        require(identity.get("imageId") == image_id, "D3_FEED_API_CHANGED")
        snapshot = _publication_snapshot(flow, observed)
        require(read_identity() == identity, "D3_FEED_API_CHANGED")
        return identity, snapshot
    identity, before = capture()
    result = recreate()
    require(isinstance(result, dict) and result.get("status") == "PASS", "D3_FEED_RECREATE_NOT_PROVEN")
    current, after = capture()
    require(current.get("containerId") != identity.get("containerId")
            and current.get("startedAt") != identity.get("startedAt"), "D3_FEED_RECREATE_NOT_PROVEN")
    require(before == after, "D3_FEED_METADATA_CHANGED")
    return {**result, "publicationPersistence": {"status": "PASS", "scope": "PUBLISHED_VIDEO_RECREATE",
        "jobId": observed["jobId"], "galleryId": observed["galleryId"], "publicationId": observed["publicationId"],
        "browserRunId": browser["runId"], **after,
        "apiBefore": identity, "apiAfter": current, "privateAccess": "PASS",
        "mediaProof": "IDENTICAL_TO_PRE_RECREATE_BROWSER_DECODE", "modelExecution": False, "acceleratorExecution": False}}


def browser_run(payload, directory, report, *, run_id=None):
    environment = {key: os.environ[key] for key in HOST_ENV if key in os.environ}
    finished, execution_error = None, None
    try:
        finished = subprocess.run([sys.executable, str(ROOT / "tools/docker_d3_process.py"),
            str(ROOT / "tools/docker_d3_chat_video.mjs"), str(directory)],
            input=json.dumps(payload).encode("utf-8"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=150, cwd=ROOT, env=environment, check=False)
    except subprocess.TimeoutExpired:
        execution_error = "D3_SUPERVISOR_TIMEOUT"
    except OSError:
        execution_error = "D3_SUPERVISOR_UNAVAILABLE"
    finally:
        payload.clear()
    # The independent immutable image checkpoint survives a later video or process failure.
    checkpoint = directory / "chat-video-image.json"
    if checkpoint.exists():
        partial = receipt(directory, checkpoint.name)
        require(run_id is None or partial.get("runId") == run_id, "D3_BROWSER_RUN_ID_CHANGED")
        image = owned_image(partial, report["sourceSha"], report["project"])
        observed = partial.get("chatImage", {})
        require(partial.get("status") == "PARTIAL" and isinstance(observed, dict)
                and observed.get("status") == "PASS" and "errorCode" not in observed
                and observed.get("jobId") == image["jobId"]
                and isinstance(observed.get("requestId"), str)
                and re.fullmatch(r"[A-Za-z0-9_-]{1,120}", observed["requestId"])
                and type(observed.get("imageSubmits")) is int and observed["imageSubmits"] == 1,
                "D3_BROWSER_IMAGE_CHECKPOINT_INVALID")
        accepted_accounting(observed.get("accounting"), image["tokenCost"], 1)
        report["image"] = image
        report["partialBrowserRunId"] = partial["runId"]
    if (directory / "browser-process.json").exists():
        report["process"] = receipt(directory, "browser-process.json")
    if execution_error:
        raise ProductError(execution_error)
    browser = report["browser"] = receipt(directory, "chat-video-browser.json")
    require(run_id is None or browser.get("runId") == run_id, "D3_BROWSER_RUN_ID_CHANGED")
    require(browser.get("sourceSha") == report["sourceSha"] and browser.get("project") == report["project"]
            and browser.get("modelExecution") is False and browser.get("acceleratorExecution") is False,
            "D3_BROWSER_IDENTITY_MISMATCH")
    if "image" in browser:
        image = owned_image(browser, report["sourceSha"], report["project"])
        require("image" in report and image == report["image"]
                and browser["runId"] == report["partialBrowserRunId"], "D3_BROWSER_IMAGE_CHECKPOINT_CHANGED")
    clean_process(report.get("process", {}), finished.returncode)
    return browser


def prove_chat_video(flow: ProductFlow, attestation: dict, directory: Path, *, provider_receipt, phone_watch=None) -> dict:
    """Caller owns profile lifetime/cleanup; callback reads its private receipt, never HTTP control."""
    origin = validate_target(attestation)
    require(isinstance(flow, ProductFlow) and origin == flow.origin and origin.startswith("http://127.0.0.1:")
            and attestation["sourceSha"] == flow.source_sha and attestation["project"] == flow.project
            and all(client.origin == origin for client in flow.clients) and callable(provider_receipt),
            "D3_OWNED_FLOW_REQUIRED")
    credentials = {id(client): (email, password) for client, email, password in flow.credentials}
    require(id(flow.owner) in credentials and id(flow.other) in credentials, "D3_OWNED_SESSIONS_REQUIRED")
    before = provider_receipt()
    baseline = admitted_provider(before)
    require(not baseline["d3"]["chat"] and baseline["d3"]["video"] is None, "D3_FRESH_PROFILE_REQUIRED")
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    run_id, watcher = uuid.uuid4().hex, None
    report = {"status": "FAIL", "sourceSha": flow.source_sha, "project": flow.project, "runId": run_id,
              "evidenceClass": "installed-application-controlled-provider",
              "modelExecution": False, "acceleratorExecution": False}
    payload = {**attestation, "output": str(directory), "runId": run_id, "phoneActive": phone_watch is not None,
               "email": credentials[id(flow.owner)][0],
               "password": credentials[id(flow.owner)][1], "otherEmail": credentials[id(flow.other)][0],
               "otherPassword": credentials[id(flow.other)][1]}
    try:
        if phone_watch is not None:
            from tools.docker_d3_images import read_file
            require(callable(phone_watch) and hashlib.sha256(read_file(
                ROOT / "tools/docker_d3_phone_recovery.mjs", 65536)).hexdigest() == PHONE_HELPER_SHA256,
                "D3_PHONE_HELPER_SOURCE_CHANGED")
            watcher = phone_watch(directory, run_id)
            payload["ownerId"] = watcher.owner[0]
            watcher.start()  # Hold ACK must precede the browser's only existing image submit.
        try:
            browser = browser_run(payload, directory, report, run_id=run_id)
        finally:
            if watcher is not None:
                report["phoneWatch"] = watcher.close()
        accepted_browser(browser)
        if watcher is not None:
            accepted_phone_watch(report["phoneWatch"], browser)
        # The in-process recorder runs every .2s; wait only for its owned final download record.
        for _ in range(8):
            after = provider_receipt()
            if (admitted_provider(after)["d3"].get("video") or {}).get("downloads") == 1:
                break
            time.sleep(.25)
        report["provider"] = correlate(before, after, browser, phone_watch=report.get("phoneWatch"))
        report["status"] = "PASS"
    except Exception as error:
        code = str(error)
        report["errorCode"] = code if isinstance(error, ProductError) and re.fullmatch(r"D3_[A-Z0-9_]{2,100}", code) else "D3_RUNTIME_FAILED"
        browser_error = report.get("browser", {}).get("errorCode")
        if isinstance(browser_error, str) and re.fullmatch(r"D3_[A-Z0-9_]{2,100}", browser_error):
            report["errorCode"] = browser_error
    finally:
        if watcher is not None:
            report["phoneWatch"] = watcher.close()
        payload.clear()
        with (directory / "chat-video.json").open("x", encoding="utf-8") as output:
            os.chmod(output.name, 0o600)
            json.dump(report, output, indent=2)
            output.write("\n")
    return report
