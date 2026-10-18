"""Run mocked-API Phone UI checks only in a disposable hosted Linux CI checkout."""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid


EXPECTED_HELPER_SHA = "37c32cf6a6ba66b0e45ad8b79c3e860f6ee49eea3b1415ac787066c268f6589a"
LIMIT = 16384
SHA = re.compile(r"[0-9a-f]{40}")
CASE_NAMES = tuple(name for width in (390, 430) for name in (
    f"image-{width}-completed", f"image-{width}-cancelled",
    f"image-{width}-spa-unmount", f"video-{width}-spa-unmount",
    f"image-{width}-recovery-retry"))


class UiFailure(RuntimeError):
    pass


def require(condition, code):
    if not condition:
        raise UiFailure(code)


def bounded_file(path, limit, *, private=False):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and 0 <= info.st_size <= limit and info.st_nlink == 1,
                "D3_PHONE_UI_FILE_INVALID")
        if private:
            require(stat.S_IMODE(info.st_mode) == 0o600, "D3_PHONE_UI_FILE_INVALID")
        data = source.read(limit + 1)
    require(len(data) <= limit, "D3_PHONE_UI_FILE_INVALID")
    return data


def digest(data):
    return hashlib.sha256(data).hexdigest()


class ReleaseParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.labels = []

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "meta" and fields.get("name") == "izo-release":
            self.labels.append(fields.get("content"))


def require_ci(environment):
    require(sys.platform == "linux" and os.getuid() != 0
            and environment.get("GITHUB_ACTIONS") == "true"
            and environment.get("RUNNER_ENVIRONMENT") == "github-hosted",
            "D3_PHONE_UI_CI_SCOPE_INVALID")


def create_output(output, environment):
    temp = Path(environment.get("RUNNER_TEMP", "")).resolve()
    require(environment.get("RUNNER_TEMP") and output.is_absolute() and output == output.resolve()
            and output.parent == temp and temp.is_dir(), "D3_PHONE_UI_OUTPUT_INVALID")
    output.mkdir(mode=0o700)
    require(stat.S_IMODE(output.stat().st_mode) == 0o700, "D3_PHONE_UI_OUTPUT_INVALID")


def prepare(root, output, source_sha, environment):
    require(SHA.fullmatch(source_sha) and environment.get("GITHUB_SHA") == source_sha,
            "D3_PHONE_UI_SOURCE_INVALID")
    values = [environment.get(key, "") for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB")]
    require(re.fullmatch(r"[0-9]{1,20}", values[0]) and re.fullmatch(r"[0-9]{1,8}", values[1])
            and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", values[2]), "D3_PHONE_UI_JOB_INVALID")
    helper = bounded_file(root / "frontend/phoneJobRecovery.ui.mjs", 24576)
    require(digest(helper) == EXPECTED_HELPER_SHA, "D3_PHONE_UI_HELPER_MISMATCH")
    index = bounded_file(root / "frontend/dist/index.html", 65536)
    parser = ReleaseParser()
    parser.feed(index.decode("utf-8"))
    require(parser.labels == [source_sha], "D3_PHONE_UI_BUILD_MISMATCH")
    runner = bounded_file(root / "tools/docker_d3_phone_ui.mjs", 24576)
    process_source = bounded_file(root / "tools/docker_d3_process.py", 24576)
    return {"schema": "izo-d3-phone-ui/v1", "sourceSha": source_sha,
            "jobIdentity": ".".join(values), "runId": uuid.uuid4().hex, "output": str(output),
            "helperSha256": digest(helper), "buildIndexSha256": digest(index),
            "runnerSha256": digest(runner), "supervisorSha256": digest(process_source)}


def validate_browser(value, expected):
    require(isinstance(value, dict), "D3_PHONE_UI_RECEIPT_INVALID")
    for key in ("schema", "sourceSha", "jobIdentity", "runId", "helperSha256", "buildIndexSha256", "runnerSha256"):
        require(value.get(key) == expected[key], "D3_PHONE_UI_IDENTITY_MISMATCH")
    require(value.get("status") == "PASS" and value.get("browserCleanup") == "PASS"
            and value.get("serverCleanup") == "PASS" and "errorCode" not in value,
            "D3_PHONE_UI_EXECUTION_FAILED")
    proof = value.get("proof", {})
    require(isinstance(proof, dict) and proof.get("status") == "PASS"
            and proof.get("evidenceClass") == "mocked-api-real-phone-ui"
            and proof.get("installedAcceptance") == "NOT_VERIFIED"
            and proof.get("uiCancellation") == "NOT_SUPPORTED"
            and proof.get("modelExecution") is False and proof.get("acceleratorExecution") is False,
            "D3_PHONE_UI_PROOF_INVALID")
    cases = proof.get("cases")
    require(isinstance(cases, list) and len(cases) == 10 and all(isinstance(case, dict) for case in cases),
            "D3_PHONE_UI_CASES_INVALID")
    require(all(isinstance(case.get("case"), str) for case in cases)
            and sorted(case["case"] for case in cases) == sorted(CASE_NAMES), "D3_PHONE_UI_CASES_INVALID")
    for case in cases:
        require(case.get("status") == "PASS" and "errorCode" not in case, "D3_PHONE_UI_CASES_INVALID")
        if case["case"].endswith("spa-unmount"):
            require(case.get("signalAborted") is True and type(case.get("furtherReads")) is int
                    and case["furtherReads"] == 0, "D3_PHONE_UI_CASES_INVALID")
        else:
            require(case.get("sameJobId") == "phone-ui-owned-image"
                    and type(case.get("generatedRequests")) is int and case["generatedRequests"] == 0,
                    "D3_PHONE_UI_CASES_INVALID")
            if case["case"].endswith("recovery-retry"):
                require(case.get("recoveryRetried") is True and case.get("pollingRetried") is True,
                        "D3_PHONE_UI_CASES_INVALID")
    return value


def validate_process(process):
    require(isinstance(process, dict) and process.get("status") == "PASS"
            and process.get("scope") == "PRIVATE_LINUX_SUBREAPER"
            and type(process.get("nodeReturncode")) is int and process["nodeReturncode"] == 0
            and process.get("timedOut") is False and "errorCode" not in process,
            "D3_PHONE_UI_PROCESS_FAILED")
    cleanup = process.get("cleanup", {})
    require(isinstance(cleanup, dict) and cleanup.get("status") == "PASS"
            and cleanup.get("remainingUnknown") is False and cleanup.get("overflow") is False
            and cleanup.get("errors") == [] and all(type(cleanup.get(key)) is int and cleanup[key] == 0
                for key in ("childrenAtShutdown", "remainingChildren")), "D3_PHONE_UI_PROCESS_FAILED")


def save(path, value):
    encoded = (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode()
    require(len(encoded) <= LIMIT, "D3_PHONE_UI_RECEIPT_LIMIT")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(encoded)


def run(root, output, source_sha, environment, *, supervisor=None, clock=time.monotonic):
    started = clock()
    report = {"status": "FAIL", "sourceSha": source_sha if SHA.fullmatch(source_sha) else None,
              "evidenceClass": "mocked-api-real-phone-ui", "installedAcceptance": "NOT_VERIFIED",
              "modelExecution": False, "acceleratorExecution": False, "process": {"status": "NOT_RUN"}}
    admitted_output = False
    try:
        require_ci(environment)
        create_output(output, environment)
        admitted_output = True
        payload = prepare(root, output, source_sha, environment)
        if supervisor is None:
            from tools.docker_d3_process import supervise
            supervisor = supervise
        report.update({key: payload[key] for key in ("runId", "jobIdentity", "helperSha256", "supervisorSha256")})
        remaining = 140 - (clock() - started)
        require(0 < remaining <= 140, "D3_PHONE_UI_DEADLINE_EXCEEDED")
        process = supervisor(["node", str(root / "tools/docker_d3_phone_ui.mjs")],
            json.dumps(payload).encode(), cwd=root, timeout=remaining)
        report["process"] = process
        validate_process(process)
        browser = validate_browser(json.loads(bounded_file(output / "phone-ui-browser.json", LIMIT, private=True)), payload)
        report.update(status="PASS", browser=browser)
    except UiFailure as failure:
        report["errorCode"] = str(failure)
    except BaseException:
        report["errorCode"] = "D3_PHONE_UI_RUN_FAILED"
    report["seconds"] = round(clock() - started, 3)
    if admitted_output:
        try:
            save(output / "phone-ui.json", report)
        except BaseException:
            report.update(status="FAIL", errorCode="D3_PHONE_UI_RECEIPT_FAILED")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report = run(root, args.output, args.source_sha, os.environ)
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
