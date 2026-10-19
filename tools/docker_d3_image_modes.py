"""Remaining published image modes through an attested D3 application and wire fixture."""
from __future__ import annotations

import copy
import hashlib
import re
import time

from tools.docker_d3_chat_video import admitted_provider
from tools.docker_d3_chat_video_provider import FACE_LORAS
from tools.docker_shadow_product import ProductError, ProductFlow, path_id, require, validate_target

MODES = ("edit", "paint", "faceswap")
PUBLISHED = ("text_to_image", "image_to_image", *MODES)
# Valid 16x16 RGB PNG with a red diagonal; canvas uses the real data-image decoder.
CANVAS = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAVElEQVR4nJXLwQkAIAwDwKzhEO6/h7uI+FMQSqm1jZDS5HFope70McngAN5g35fBebyBNNJAD8bA7NRYkBoHxMYHgXmCl4mAaxJwmxwYQwFtWCBmASjOkknfO0b6AAAAAElFTkSuQmCC"


def payload(mode: str, source_url: str) -> dict:
    require(mode in MODES and isinstance(source_url, str)
            and re.fullmatch(r"/api/media/[A-Za-z0-9_-][A-Za-z0-9_.-]{0,219}(?:\?userId=web_[0-9a-f]{32})?", source_url),
            "D3_IMAGE_INPUT_INVALID")
    body = {"mode": mode, "provider": "comfyui", "prompt": "Owned geometric fixture",
            "width": 704, "height": 704, "steps": 4, "seed": 18732}
    if mode == "paint":
        body["canvas"] = CANVAS
    else:
        body["inputImage1"] = source_url
        if mode == "faceswap":
            body["inputImage2"] = source_url
    return body


def settlement(before: dict, after: dict, started: dict) -> dict:
    cost = started.get("tokenCost")
    require(type(cost) is int and cost > 0, "D3_IMAGE_COST_INVALID")
    job_id = path_id(started.get("id"))
    public_id = job_id[:10] + ("…" if len(job_id) > 10 else "")
    previous = {item["id"]: item for item in before["ledger"]["items"]}
    current = {item["id"]: item for item in after["ledger"]["items"]}
    require(len(previous) == len(before["ledger"]["items"])
            and len(current) == len(after["ledger"]["items"])
            and previous.keys() <= current.keys()
            and all(current[key] == value for key, value in previous.items()),
            "D3_IMAGE_LEDGER_BASELINE_CHANGED")
    new = [item for key, item in current.items() if key not in previous]
    left, right = before["ledger"]["summary"], after["ledger"]["summary"]
    require(before["identity"] == after["identity"]
            and right["spentTokens"] - left["spentTokens"] == cost
            and right["refundedTokens"] == left["refundedTokens"]
            and len(new) == 1 and type(new[0].get("spentTokens")) is int
            and new[0]["spentTokens"] == cost,
            "D3_IMAGE_SINGLE_CHARGE_NOT_PROVEN")
    charge = new[0]
    require(charge.get("jobId") == public_id and charge.get("mode") == started.get("mode") in MODES
            and charge.get("provider") == started.get("provider") == "comfyui"
            and isinstance(charge["id"], str) and re.fullmatch(r"[A-Za-z0-9_-]{1,120}…?", charge["id"]),
            "D3_IMAGE_CHARGE_PROVENANCE_INVALID")
    require(after["account"] == {"token_balance": started["tokenBalance"],
                                "daily_tokens_used": started["dailyTokensUsed"]},
            "D3_IMAGE_ACCOUNT_MISMATCH")
    balance = before["account"]["token_balance"] - after["account"]["token_balance"]
    daily = after["account"]["daily_tokens_used"] - before["account"]["daily_tokens_used"]
    require(all(type(value) is int for value in (*before["account"].values(), *after["account"].values(),
                *left.values(), *right.values(), charge.get("delta"), started.get("mainBalanceTokenPart"),
                started.get("dailyTokenPart"), started.get("tokenBalance"), started.get("dailyTokensUsed")))
            and min(balance, daily) >= 0 and balance + daily == cost
            and balance == started["mainBalanceTokenPart"] and daily == started["dailyTokenPart"]
            and charge["delta"] == -balance
            and charge.get("reason") == ("daily_generation" if daily == cost else "generation")
            and right["balanceSpentTokens"] - left["balanceSpentTokens"] == balance
            and right["includedSpentTokens"] - left["includedSpentTokens"] == daily
            and left["balance"] == before["account"]["token_balance"]
            and right["balance"] == after["account"]["token_balance"], "D3_IMAGE_DEBIT_MISMATCH")
    return {"singleCharge": True, "tokenCost": cost, "ledgerId": charge["id"], "publicJobId": public_id,
            "mode": started["mode"], "provider": "comfyui", "mainBalanceDebit": balance,
            "dailyBudgetDebit": daily, "refundDelta": 0, "fullJobLedgerLinkage": "NOT_VERIFIED"}


def completed(flow: ProductFlow, job_id: str, *, deadline: float) -> tuple[dict, list[str]]:
    states = set()
    while True:
        require(time.monotonic() < deadline, "D3_IMAGE_JOB_TIMEOUT")
        job = flow.owner.request("GET", f"/api/jobs/{job_id}")
        # A late HTTP response cannot establish completion within the polling budget.
        require(time.monotonic() < deadline, "D3_IMAGE_JOB_TIMEOUT")
        state = job.get("status")
        require(state in {"queued", "running", "uploading", "sent_to_comfyui", "completed"},
                "D3_IMAGE_JOB_FAILED")
        states.add(state)
        if state == "completed":
            require(job.get("id") == job_id and type(job.get("progress")) is int and job["progress"] == 100,
                    "D3_IMAGE_COMPLETION_INVALID")
            return job, sorted(states)
        time.sleep(.2)


def phone_result(value: dict, started: dict, image: dict) -> None:
    from tools.docker_clean_features import public_fields

    phone = value.get("job")
    require(value.get("ok") is True and isinstance(phone, dict) and public_fields(value),
            "D3_IMAGE_PHONE_RESULT_MISMATCH")
    result, billing = phone.get("result"), phone.get("billing")
    require(isinstance(result, dict) and isinstance(billing, dict)
            and phone.get("id") == started["id"] and phone.get("operation") == started["mode"]
            and phone.get("modality") == "image" and phone.get("status") == "completed"
            and phone.get("terminal") is True and phone.get("phase") == "terminal"
            and type(phone.get("progress")) is int and phone["progress"] == 100
            and result.get("id") == image["id"] and result.get("type") == "image"
            and result.get("url") == image["url"]
            and type(billing.get("chargedTokens")) is int and billing["chargedTokens"] == started["tokenCost"]
            and billing.get("refunded") is False, "D3_IMAGE_PHONE_RESULT_MISMATCH")


def provider_result(before: dict, after: dict, job_id: str, mode: str) -> dict | None:
    left, right = admitted_provider(before), admitted_provider(after)
    require(before["instanceId"] == after["instanceId"], "D3_IMAGE_PROVIDER_INSTANCE_CHANGED")
    for value in (left, right):
        jobs = value["jobs"]
        require(all(isinstance(item, dict) for item in jobs), "D3_IMAGE_PROVIDER_JOBS_INVALID")
        for field, pattern in (("prompt_id", r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}"),
                               ("client_sha256", r"[a-f0-9]{64}"), ("body_sha256", r"[a-f0-9]{64}")):
            values = [item.get(field) for item in jobs]
            require(all(isinstance(item, str) and re.fullmatch(pattern, item) for item in values)
                    and len(set(values)) == len(values), "D3_IMAGE_PROVIDER_REPLAY_OR_DIGEST_INVALID")
        accepted = value.get("counts", {}).get("accepted", 0)
        require(type(accepted) is int and accepted == len(jobs), "D3_IMAGE_PROVIDER_COUNT_INVALID")
    previous = {item["prompt_id"]: item for item in left["jobs"]}
    current = {item["prompt_id"]: item for item in right["jobs"]}
    require(previous.keys() <= current.keys() and all(current[key] == item for key, item in previous.items()),
            "D3_IMAGE_PROVIDER_BASELINE_CHANGED")
    new = [item for key, item in current.items() if key not in previous]
    if not new:
        return None  # The bounded recorder may not yet contain this submit.
    expected_client = hashlib.sha256(("onenode-backend-" + path_id(job_id)).encode()).hexdigest()
    require(len(new) == 1 and new[0]["client_sha256"] == expected_client
            and new[0].get("state") == "completed" and new[0].get("mode") == "complete",
            "D3_IMAGE_PROVIDER_SUBMIT_MISMATCH")
    graph = new[0].get("graph")
    if graph is None:
        return None  # Recorder can observe the short interval before graph facts are attached.
    require(mode in MODES and isinstance(graph, dict) and set(graph) == {
                "loadImageCount", "allInputsOwned", "inputChainConnected", "loraCount", "selectedFaceLora", "allLorasAllowed"}
            and type(graph["loadImageCount"]) is int and graph["loadImageCount"] == (2 if mode == "faceswap" else 1)
            and graph["allInputsOwned"] is True and graph["inputChainConnected"] is True
            and graph["allLorasAllowed"] is True and type(graph["loraCount"]) is int
            and graph["loraCount"] == (1 if mode == "faceswap" else 0)
            and (graph["selectedFaceLora"] in FACE_LORAS if mode == "faceswap" else graph["selectedFaceLora"] is None),
            "D3_IMAGE_PROVIDER_GRAPH_MISMATCH")
    return {"promptId": new[0]["prompt_id"], "clientSha256": expected_client,
            "bodySha256": new[0]["body_sha256"], "graph": dict(graph)}


def wait_provider(before: dict, callback, job_id: str, mode: str) -> tuple[dict, dict]:
    deadline = time.monotonic() + 5
    for _ in range(26):
        require(time.monotonic() < deadline, "D3_IMAGE_PROVIDER_RECEIPT_TIMEOUT")
        after = callback()
        require(time.monotonic() < deadline, "D3_IMAGE_PROVIDER_RECEIPT_TIMEOUT")
        result = provider_result(before, after, job_id, mode)
        if result is not None:
            return result, copy.deepcopy(after)
        time.sleep(.2)
    raise ProductError("D3_IMAGE_PROVIDER_RECEIPT_TIMEOUT")


def admit_flow(flow, attestation, provider_receipt, checkpoint):
    origin = validate_target(attestation)
    require(isinstance(flow, ProductFlow) and flow.origin == origin
            and flow.source_sha == attestation["sourceSha"] and flow.project == attestation["project"]
            and flow.clients == (flow.owner, flow.other, flow.guest) and len({id(c) for c in flow.clients}) == 3
            and all(client.origin == origin for client in flow.clients) and callable(provider_receipt)
            and (checkpoint is None or callable(checkpoint)), "D3_IMAGE_OWNED_FLOW_REQUIRED")


def prove_image_modes(flow: ProductFlow, source_image: dict, *, attestation: dict,
                      provider_receipt, checkpoint=None, case_proof=None) -> dict:
    """Public/wire proof; accepted D3 calls the strict entry in docker_d3_image_ledger.

    Caller owns lifetime/cleanup and fixed private provider reads (<=64KiB, <=8s).
    Three sequential jobs; polling budgets are not an SLO. HTTP uses an 8s socket timeout.
    case_proof supplements each completed mode before PASS; public short IDs alone never prove full linkage.
    """
    admit_flow(flow, attestation, provider_receipt, checkpoint)
    require(case_proof is None or callable(case_proof), "D3_IMAGE_PRIVATE_PROOF_REQUIRED")
    report = {"status": "FAIL", "sourceSha": flow.source_sha, "project": flow.project,
              "evidenceClass": "installed-application-controlled-provider", "modelExecution": False,
              "acceleratorExecution": False, "graphEvidence": "WIRE_PREPARATION_ONLY",
              "fullJobLedgerLinkage": "NOT_VERIFIED",
              "D1TextAndVariation": "REUSE_SAME_SOURCE_D1_RECEIPT", "modes": {}}

    def save():
        if checkpoint is not None:
            try:
                checkpoint(copy.deepcopy(report))
            except Exception:
                raise ProductError("D3_IMAGE_CHECKPOINT_FAILED") from None

    row = None
    try:
        wire_before = copy.deepcopy(provider_receipt())
        provider_result(wire_before, wire_before, "baseline", "edit")  # Validate before any application request.
        source_id = path_id(source_image.get("id"))
        source = flow.owner.request("GET", f"/api/gallery/{source_id}")
        require(source.get("id") == source_id and source.get("url") == source_image.get("url"),
                "D3_IMAGE_SOURCE_MISMATCH")
        source_url = source["url"]
        payload("edit", source_url)  # Validate the owned media path before following it.
        identity_before = flow.account_snapshot(flow.owner)
        legacy_id = identity_before["identity"].get("legacy_user_id")
        require(isinstance(legacy_id, str) and re.fullmatch(r"web_[0-9a-f]{32}", legacy_id),
                "D3_IMAGE_OWNED_WEB_ID_REQUIRED")
        require("?" not in source_url or source_url.endswith("?userId=" + legacy_id),
                "D3_IMAGE_SOURCE_OWNER_QUERY_MISMATCH")
        source_digest = flow.media_hash(flow.owner, source_url)
        report.update(sourceImageId=source_id, sourceSha256=source_digest)
        bootstrap = flow.owner.request("POST", "/api/app/bootstrap", {
            "platform": "web", "language": "ru", "userId": legacy_id})
        require(bootstrap.get("user", {}).get("id") == legacy_id
                and flow.account_snapshot(flow.owner) == identity_before,
                "D3_IMAGE_BOOTSTRAP_IDENTITY_CHANGED")
        advertised = bootstrap.get("features", {}).get("modes")
        require(isinstance(advertised, list) and len(advertised) == len(PUBLISHED)
                and set(advertised) == set(PUBLISHED), "D3_IMAGE_PUBLISHED_MODES_CHANGED")
        outsider_before = flow.account_snapshot(flow.other)
        require(outsider_before["identity"].get("legacy_user_id") != legacy_id,
                "D3_IMAGE_DISTINCT_OWNER_REQUIRED")
        denial = flow.other.request("POST", "/api/generate", payload("edit", source_url), expected=(400,))
        require(denial.get("httpStatus") == 400, "D3_IMAGE_FOREIGN_INPUT_STATUS_INVALID")
        require(flow.account_snapshot(flow.other) == outsider_before, "D3_IMAGE_FOREIGN_INPUT_CHARGED")
        report.update(publishedModes=advertised, foreignInputStatus=400, foreignInputDeniedWithoutCharge=True)
        for mode in MODES:
            row = report["modes"][mode] = {"status": "RUNNING"}
            before = flow.account_snapshot(flow.owner)
            started_at = time.monotonic()
            started = flow.owner.request("POST", "/api/generate", payload(mode, source_url))
            job_id = path_id(started.get("id"))
            row["jobId"] = job_id
            require(started.get("status") == "queued" and started.get("mode") == mode
                    and started.get("provider") == "comfyui", "D3_IMAGE_NOT_QUEUED")
            save()
            flow.other.request("GET", f"/api/jobs/{job_id}", expected=(404,))
            job, states = completed(flow, job_id, deadline=started_at + 45)
            image_id = path_id(job.get("resultImageId"))
            require(image_id != source_id and all(item.get("imageId") != image_id for item in report["modes"].values()),
                    "D3_IMAGE_OUTPUT_REUSED")
            image = flow.owner.request("GET", f"/api/gallery/{image_id}")
            require(image.get("id") == image_id and image.get("mode") == mode
                    and job.get("mode") == mode and job.get("provider") == image.get("provider") == "comfyui"
                    and image.get("url") == job.get("resultUrl"), "D3_IMAGE_RESULT_PROVENANCE_INVALID")
            payload("edit", image["url"])
            require("?" not in image["url"] or image["url"].endswith("?userId=" + legacy_id),
                    "D3_IMAGE_RESULT_OWNER_QUERY_MISMATCH")
            digest = flow.media_hash(flow.owner, image["url"])
            row.update(imageId=image_id, observedStates=states, mediaSha256=digest)
            phone_result(flow.owner.request("GET", f"/api/phone/v1/jobs/{job_id}"), started, image)
            for client, expected in ((flow.guest, (401,)), (flow.other, (404,))):
                client.request("GET", f"/api/phone/v1/jobs/{job_id}", expected=expected)
                client.request("GET", image["url"], expected=(401, 403, 404))
            after = flow.account_snapshot(flow.owner)
            accounting = settlement(before, after, started)
            wire, wire_before = wait_provider(wire_before, provider_receipt, job_id, mode)
            flow.owner.request("GET", f"/api/jobs/{job_id}")
            require(flow.account_snapshot(flow.owner) == after, "D3_IMAGE_POLL_CHANGED_ACCOUNT")
            row.update(accounting=accounting, provider=wire)
            if case_proof is not None:
                row["privateLedger"] = case_proof(started, accounting)
                require(isinstance(row["privateLedger"], dict) and row["privateLedger"].get("status") == "PASS"
                        and row["privateLedger"].get("fullJobLedgerLinkage") == "PASS",
                        "D3_IMAGE_PRIVATE_PROOF_REQUIRED")
            row.update(status="PASS", imageId=image_id, observedStates=states, mediaSha256=digest,
                accounting=accounting, provider=wire, phoneCompleted=True, privateMediaDenial=True,
                observedCaseSeconds=round(time.monotonic() - started_at, 3))
            save()
        require(flow.media_hash(flow.owner, source_url) == source_digest, "D3_IMAGE_SOURCE_CHANGED")
        report["status"] = "PASS"
        save()
        return report
    except Exception as error:
        code = str(error)
        code = code if isinstance(error, ProductError) and re.fullmatch(r"(?:D3|PRODUCT)_[A-Z0-9_]{2,100}", code) else "D3_IMAGE_OPERATION_FAILED"
        report.update(status="FAIL", errorCode=code)
        if row is not None and row["status"] == "RUNNING":
            row.update(status="FAIL", errorCode=code)
        if code != "D3_IMAGE_CHECKPOINT_FAILED":
            save()
        raise ProductError(code) from None
