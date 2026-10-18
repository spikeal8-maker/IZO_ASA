"""Four bounded owned snapshots bind the three controlled image modes to exact charges."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import time

from tools.docker_d3_image_modes import MODES, admit_flow, prove_image_modes
from tools.docker_d3_ledger import identifier_sha, validated
from tools.docker_shadow_product import ProductError, require

LIMIT = 65536


def safe_snapshot(value):
    """Validate the private envelope before copying or persisting any provider-supplied value."""
    validated(value)
    api = value.get("api")
    require(all(key in value for key in ("sourceSha", "project", "api"))
            and isinstance(value["sourceSha"], str) and re.fullmatch(r"[a-f0-9]{40}", value["sourceSha"])
            and isinstance(value["project"], str) and re.fullmatch(r"izo-asa-shadow-[a-z0-9][a-z0-9-]{2,39}", value["project"])
            and isinstance(api, dict) and set(api) == {"containerId", "imageId", "hostPid", "startedAt", "restartCount"}
            and isinstance(api["containerId"], str) and re.fullmatch(r"[a-f0-9]{64}", api["containerId"])
            and isinstance(api["imageId"], str) and re.fullmatch(r"sha256:[a-f0-9]{64}", api["imageId"])
            and type(api["hostPid"]) is int and api["hostPid"] > 0
            and type(api["restartCount"]) is int and api["restartCount"] >= 0
            and isinstance(api["startedAt"], str)
            and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?Z", api["startedAt"]),
            "D3_IMAGE_PRIVATE_ENVELOPE_INVALID")
    for row in value["jobs"].values():
        require(isinstance(row, dict) and set(row) == {"mode", "provider", "status"}
                and row["mode"] in MODES and row["provider"] == "comfyui" and row["status"] == "completed",
                "D3_IMAGE_PRIVATE_JOB_INVALID")
    return value


def settle_image_ledger(before, after, started, public):
    safe_snapshot(before); safe_snapshot(after)
    mode, cost, job = started.get("mode"), started.get("tokenCost"), identifier_sha(started.get("id"))
    require(mode in MODES and started.get("provider") == "comfyui" and type(cost) is int and cost > 0,
            "D3_IMAGE_PRIVATE_JOB_INVALID")
    require(all(before[key] == after[key] for key in ("ownerSha256", "sourceSha", "project", "api"))
            and len(before["requestedJobSha256"]) <= 1 and after["requestedJobSha256"] == [job]
            and before["activeOwnedJobs"] == after["activeOwnedJobs"] == 0
            and before["capturedAt"] <= after["capturedAt"]
            and before["account"]["last_daily_reset"] == after["account"]["last_daily_reset"],
            "D3_IMAGE_PRIVATE_BASELINE_CHANGED")
    old = {row["idSha256"]: row for row in before["ledger"]}
    current = {row["idSha256"]: row for row in after["ledger"]}
    require(all(current.get(key) == row for key, row in old.items())
            and all(row["jobSha256"] != job for row in old.values()), "D3_IMAGE_PRIVATE_PRIOR_ROWS_CHANGED")
    added = [row for key, row in current.items() if key not in old]
    require(len(added) == 1 and added[0]["jobSha256"] == job
            and after["jobs"][job] == {"mode": mode, "provider": "comfyui", "status": "completed"},
            "D3_IMAGE_PRIVATE_SINGLE_CHARGE_NOT_PROVEN")
    row = added[0]
    require(type(row["tokenCost"]) is int and row["tokenCost"] == cost
            and all(type(row[key]) is int and row[key] >= 0 for key in ("balancePart", "dailyPart"))
            and row["balancePart"] + row["dailyPart"] == cost and row["delta"] == -row["balancePart"]
            and row["reason"] == ("daily_generation" if row["dailyPart"] == cost else "generation")
            and row["mode"] == mode and row["provider"] == "comfyui"
            and all(row[key] is None for key in ("requestSha256", "chargedLedgerSha256", "refundTokens")),
            "D3_IMAGE_PRIVATE_DEBIT_INVALID")
    require(public.get("singleCharge") is True and public.get("fullJobLedgerLinkage") == "NOT_VERIFIED"
            and public.get("mode") == mode and public.get("provider") == "comfyui"
            and type(public.get("tokenCost")) is int and public["tokenCost"] == cost
            and type(public.get("mainBalanceDebit")) is int and public["mainBalanceDebit"] == row["balancePart"]
            and type(public.get("dailyBudgetDebit")) is int and public["dailyBudgetDebit"] == row["dailyPart"]
            and type(public.get("refundDelta")) is int and public["refundDelta"] == 0,
            "D3_IMAGE_PRIVATE_PUBLIC_MISMATCH")
    left, right = before["account"], after["account"]
    require(left["token_balance"] - right["token_balance"] == row["balancePart"]
            and right["daily_tokens_used"] - left["daily_tokens_used"] == row["dailyPart"]
            and right["tokens_used"] - left["tokens_used"] == cost
            and right["generation_count"] - left["generation_count"] == 1
            and type(started.get("tokenBalance")) is int and started["tokenBalance"] == right["token_balance"]
            and type(started.get("dailyTokensUsed")) is int and started["dailyTokensUsed"] == right["daily_tokens_used"],
            "D3_IMAGE_PRIVATE_ACCOUNT_MISMATCH")
    return {"status": "PASS", "fullJobLedgerLinkage": "PASS", "jobIdSha256": job,
            "chargeLedgerIdSha256": row["idSha256"], "mode": mode, "provider": "comfyui",
            "chargeCount": 1, "refundCount": 0, "priorRowsUnchanged": len(old), "tokenCost": cost,
            "mainBalanceDebit": row["balancePart"], "dailyBudgetDebit": row["dailyPart"]}


def write_once(directory, name, value):
    data = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    require(len(data) <= LIMIT, "D3_IMAGE_PRIVATE_RECEIPT_LIMIT")
    path = directory / (name + ".json")
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as output:
        output.write(data)
    return {"receipt": path.name, "sha256": hashlib.sha256(data).hexdigest()}, data


def write_summary(directory, proof):
    temporary = directory / "receipt-pending.json"
    try:
        reference, _ = write_once(directory, "receipt-pending", {key: value for key, value in proof.items() if key != "receipt"})
        os.replace(temporary, directory / "receipt.json")
        return {**reference, "receipt": "receipt.json"}
    finally:
        temporary.unlink(missing_ok=True)


def prove_image_modes_private(flow, source_image, directory, *, attestation, provider_receipt,
                              private_ledger, checkpoint=None):
    """Strict D3 entry; no public fallback if a private read or match fails.

    Caller creates the same-profile owned reader after image-profile recycle, enforces <=8s per read
    and the existing whole-step deadline, and owns cleanup. Exactly [] then 3 x [one full job ID].
    Four immutable <=64KiB snapshots preserve safe evidence before matching. No SQLite writes or models.
    """
    admit_flow(flow, attestation, provider_receipt, checkpoint)
    require(callable(private_ledger), "D3_IMAGE_PRIVATE_PROOF_REQUIRED")
    directory = Path(directory)
    proof = {"status": "FAIL", "fullJobLedgerLinkage": "NOT_VERIFIED", "sourceSha": flow.source_sha,
             "project": flow.project, "snapshots": [], "modes": {}}
    latest = {"status": "FAIL", "sourceSha": flow.source_sha, "project": flow.project, "modes": {}}
    created = False

    def publish(value):
        nonlocal latest
        latest = copy.deepcopy(value)
        latest["privateLedger"] = copy.deepcopy(proof)
        if checkpoint is not None:
            try:
                checkpoint(copy.deepcopy(latest))
            except Exception:
                raise ProductError("D3_IMAGE_CHECKPOINT_FAILED") from None

    def read(job_ids, label):
        require(isinstance(job_ids, list) and len(job_ids) <= 1, "D3_IMAGE_PRIVATE_SEQUENCE_INVALID")
        wanted = [identifier_sha(item) for item in job_ids]
        started_at = time.monotonic()
        value = private_ledger(list(job_ids))
        require(time.monotonic() - started_at < 8, "D3_IMAGE_PRIVATE_READ_TIMEOUT")
        safe_snapshot(value)
        require(value["sourceSha"] == flow.source_sha and value["project"] == flow.project
                and value["requestedJobSha256"] == wanted
                and -1 <= time.time() - value["capturedAt"] <= 5,
                "D3_IMAGE_PRIVATE_IDENTITY_MISMATCH")
        reference, data = write_once(directory, label, value)
        proof["snapshots"].append(reference)
        return json.loads(data), reference

    try:
        directory.mkdir(mode=0o700, exist_ok=False)
        created = True
        previous, previous_ref = read([], "00-before")
        require(previous["activeOwnedJobs"] == 0, "D3_IMAGE_PRIVATE_BASELINE_CHANGED")
        publish(latest)

        def prove_case(started, public):
            nonlocal previous, previous_ref
            index = len(proof["modes"])
            require(index < len(MODES) and started.get("mode") == MODES[index], "D3_IMAGE_PRIVATE_SEQUENCE_INVALID")
            mode = MODES[index]
            after, reference = read([started["id"]], f"{index + 1:02d}-{mode}")
            case = settle_image_ledger(previous, after, started, public)
            case.update(beforeSnapshotSha256=previous_ref["sha256"], afterSnapshotSha256=reference["sha256"])
            proof["modes"][mode] = case
            previous, previous_ref = after, reference
            return copy.deepcopy(case)

        result = prove_image_modes(flow, source_image, attestation=attestation,
            provider_receipt=provider_receipt, checkpoint=publish, case_proof=prove_case)
        require(result.get("status") == "PASS" and tuple(proof["modes"]) == MODES
                and len(proof["snapshots"]) == 4, "D3_IMAGE_PRIVATE_SEQUENCE_INVALID")
        proof.update(status="PASS", fullJobLedgerLinkage="PASS")
        proof["receipt"] = write_summary(directory, proof)
        publish(result)
        return latest
    except Exception as error:
        value = str(error)
        code = value if isinstance(error, ProductError) and re.fullmatch(r"(?:D3|PRODUCT)_[A-Z0-9_]{2,100}", value) else "D3_IMAGE_PRIVATE_OPERATION_FAILED"
        proof.update(status="FAIL", fullJobLedgerLinkage="NOT_VERIFIED", errorCode=code)
        latest.update(status="FAIL", errorCode=code)
        if created:
            try:
                proof["receipt"] = write_summary(directory, proof)
            except Exception:
                code = "D3_IMAGE_PRIVATE_RECEIPT_WRITE_FAILED"
                proof["errorCode"] = latest["errorCode"] = code
        if code != "D3_IMAGE_CHECKPOINT_FAILED":
            publish(latest)
        raise ProductError(code) from None
