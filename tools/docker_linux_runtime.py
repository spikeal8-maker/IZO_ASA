"""Hosted Linux ordinary-runtime proof using the existing builder and frozen controller."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import zipfile

import docker_linux_bundle_build as linux

sys.dont_write_bytecode = True
CONTRACT = "DOCKER-LINUX-SYNTHETIC-RUNTIME-002"
TOOLING = "b517feb365eb7dcb0047f92500d73d4e82a74bff"
PROJECT = "izo-asa-bundle-runtime-linux01"
PORTS = {"web": 48774, "api": 48775}
SECONDS = 420
RUN_TIMEOUT, CLEANUP_TIMEOUT, DAY_MARGIN = 1500, 240, 60
COMMON = "2192a7aef412442850e25b73945c2c8e773859844ca77bcb5849d681ae2e6913"
CONTROLLERS = {"synthetic_runtime_accept.py": "013b4e10448d091a7e4817dde33c8002dd23437e58450826493972504e52f1e1",
               "synthetic_runtime_checks.py": "d7a2f251194b2ef1e79776bd4325b126afa4d6e5cd0c725bf0111eb71b977663"}
PASS = "PASS_ORDINARY_SYNTHETIC_RUNTIME_LINUX_ONLY"
require = linux.require


def canonical(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def read(path):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 4 * 1024**2, "RECEIPT_INPUT_INVALID")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    require(type(value) is dict, "RECEIPT_OBJECT_REQUIRED")
    return value


def safe(error):
    value = str(error)
    return value if re.fullmatch(r"[A-Z][A-Z0-9_]{1,100}", value) else "RUNTIME_LINUX_CONTRACT_FAILED"


def sources(args, runner):
    for path, sha in ((args.candidate, runner["head"]), (args.tooling, TOOLING), (args.source_b, linux.SOURCES["B"])):
        linux.source_guard(path, sha)
    common = args.candidate / "tools/docker_linux_bundle_build.py"
    require(Path(linux.__file__).resolve() == common.resolve() and canonical(common) == COMMON, "COMMON_PROOF_HELPER_CHANGED")
    require(platform.python_version() == (args.candidate / ".python-version").read_text().strip(), "PINNED_PYTHON_REQUIRED")
    for name, pin in CONTROLLERS.items():
        require(canonical(args.candidate / "tools" / name) == pin, "FROZEN_CONTROLLER_CHANGED")
    require(not args.root.resolve().is_relative_to(args.tooling.resolve())
            and not args.root.resolve().is_relative_to(args.candidate.resolve())
            and not args.source_b.resolve().is_relative_to(args.tooling.resolve()), "WORK_OR_SOURCE_INSIDE_CHECKOUT")


def support(args):
    return {"toolingRoot": str(args.tooling),
            "moduleHashes": {name: canonical(args.tooling / "tools" / (name + ".py"))
                             for name in ("docker_test_bundle_format", "docker_test_bundle_runtime")},
            "httpClientPath": str(args.source_b / "tools/docker_shadow_product.py"),
            "httpClientSha256": canonical(args.source_b / "tools/docker_shadow_product.py")}


def manifest(archive, receipt, source):
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        require(names.count("bundle.json") == 1 and bundle.getinfo("bundle.json").file_size <= 2 * 1024**2,
                "BUNDLE_METADATA_INVALID")
        body = bundle.read("bundle.json")
    require(hashlib.sha256(body).hexdigest() == receipt["manifest_sha256"], "BUNDLE_MANIFEST_CHANGED")
    value = json.loads(body)
    require(value.get("format") == 2 and value.get("profile") == "synthetic-runtime"
            and value.get("source_sha") == source and value.get("tooling_sha") == TOOLING
            and value.get("project") == PROJECT and value.get("ports") == PORTS
            and set(value.get("images", {})) == {"backend", "web", "guard"}
            and value.get("production_authorized") is False and value.get("model_execution") is False,
            "ORDINARY_PROFILE_REQUIRED")
    return value


def validate_release(root, label, record):
    archive = root / ("release-" + label + ".zip")
    path = archive.with_suffix(".receipt.json"); receipt = read(path)
    require(record["receiptSha256"] == linux.digest(path) and record["receipt"] == receipt
            and receipt.get("status") == "TEST_BUNDLE_BUILT" and receipt.get("source_sha") == linux.SOURCES[label]
            and receipt.get("tooling_sha") == TOOLING and receipt.get("project") == PROJECT
            and receipt.get("images_embedded") is True and receipt.get("production_authorized") is False
            and receipt.get("archive_bytes") == archive.stat().st_size
            and receipt.get("archive_sha256") == linux.digest(archive), "TRANSFER_RELEASE_CHANGED")
    return manifest(archive, receipt, linux.SOURCES[label])


def build_release(args, label, report):
    source = args.source_a if label == "A" else args.source_b
    linux.source_guard(source, linux.SOURCES[label])
    require(not source.resolve().is_relative_to(args.tooling.resolve()), "SOURCE_INSIDE_TOOLING")
    pins = linux.pinned_dockerfiles(source)
    environment = {**linux.environment(), "IZO_SOURCE_SHA": linux.SOURCES[label], "IZO_COMPOSE_PROJECT": PROJECT,
                   "IZO_SHADOW_WEB_PORT": str(PORTS["web"]), "IZO_SHADOW_API_PORT": str(PORTS["api"])}
    command = ["docker", "--context", "default", "compose", "--env-file", os.devnull, "--project-name", PROJECT]
    for name in ("compose.yml", "compose.shadow.yml"):
        command += ["-f", str(source / "ops/docker/dev" / name)]
    report["stage"] = "ordinary_images_" + label
    linux.run(command + ["build", "--no-cache", "guard", "backend", "web"], env=environment, timeout=1800)
    archive = args.root / ("release-" + label + ".zip")
    report["stage"] = "ordinary_archive_" + label
    linux.run([sys.executable, "-B", "-m", "tools.docker_test_bundle", "build", "--source", str(source),
               "--sha", linux.SOURCES[label], "--project", PROJECT, "--web-port", str(PORTS["web"]),
               "--api-port", str(PORTS["api"]), "--context", "default", "--output", str(archive),
               "--profile", "synthetic-runtime"], cwd=args.tooling, timeout=600)
    path = archive.with_suffix(".receipt.json")
    record = {"receipt": read(path), "receiptSha256": linux.digest(path), "dockerfiles": pins}
    value = validate_release(args.root, label, record)
    record["profile"] = value["profile"]
    linux.source_guard(source, linux.SOURCES[label])
    return record


def transfer(args, runner, engine):
    expected = os.environ.get("IZO_PRODUCER_RECEIPT_SHA256", "")
    require(re.fullmatch(r"[0-9a-f]{64}", expected) and linux.digest(args.transfer / "producer.json") == expected,
            "PRODUCER_RECEIPT_PIN_MISMATCH")
    producer = read(args.transfer / "producer.json")
    require(producer.get("contract") == CONTRACT and producer.get("status") == "PASS_ORDINARY_PRODUCER_ONLY"
            and producer.get("toolingSha") == TOOLING and producer.get("profile") == "synthetic-runtime"
            and producer.get("before") == {"images": [], "containers": [], "volumes": []}, "PRODUCER_CONTRACT_CHANGED")
    prior = producer["runner"]
    require(all(prior[k] == runner[k] for k in ("head", "runId", "attempt"))
            and prior["job"] == "producer" and runner["job"] == "receiver", "SEPARATE_JOB_REQUIRED")
    require(prior["bootFingerprint"] != runner["bootFingerprint"], "DISTINCT_BOOT_REQUIRED")
    for metadata, host in ((producer["engine"], prior), (engine, runner)):
        require(metadata.get("engineInstanceFingerprint") == linux.engine_instance_fingerprint(metadata, host["bootFingerprint"]),
                "ENGINE_INSTANCE_CHANGED")
    require(producer["engine"]["engineInstanceFingerprint"] != engine["engineInstanceFingerprint"], "DISTINCT_ENGINE_REQUIRED")
    actual = support(args)
    require(producer["moduleHashes"] == actual["moduleHashes"] and producer["httpClientSha256"] == actual["httpClientSha256"]
            and producer["controllerHashes"] == CONTROLLERS, "SUPPORT_TRANSFER_CHANGED")
    for label in ("A", "B"):
        validate_release(args.transfer, label, producer["releases"][label])
    return producer


def make_plan(args, producer, engine):
    return {"version": 1, "scope": {"os": "linux", "host": platform.node(), "context": "default",
                "engineFingerprint": engine["fingerprint"], "project": PROJECT, "root": str(args.root), "ports": PORTS},
            "toolingSha": TOOLING, "support": support(args), "controllerHashes": CONTROLLERS,
            "observationSeconds": SECONDS, "retainSyntheticCredentials": False,
            "bundles": {label: {"archiveSha256": record["receipt"]["archive_sha256"],
                                "manifestSha256": record["receipt"]["manifest_sha256"], "receiptSha256": record["receiptSha256"]}
                        for label, record in producer["releases"].items()}}


def controller(args, action, plan_pin, receipt_pin=None):
    command = [sys.executable, "-B", str(args.candidate / "tools/synthetic_runtime_accept.py"), action,
               "--plan", str(args.root / "plan.json"), "--plan-sha256", plan_pin]
    if receipt_pin:
        command += ["--acceptance-receipt-sha256", receipt_pin]
    process = subprocess.Popen(command, env=linux.environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    try:
        output, error = process.communicate(timeout=RUN_TIMEOUT if action == "run" else CLEANUP_TIMEOUT)
    except subprocess.TimeoutExpired:
        require(os.getpgid(process.pid) == process.pid, "CONTROLLER_PROCESS_GROUP_CHANGED")
        os.killpg(process.pid, signal.SIGKILL)  # Only the newly created controller process group; never Docker resources.
        process.communicate(timeout=10)
        raise linux.ProofError("CONTROLLER_DEADLINE_RESOURCES_RETAINED") from None
    require(len(output) <= 1024**2 and len(error) <= 1024**2, "CONTROLLER_OUTPUT_TOO_LARGE")
    require(process.returncode == 0, "CONTROLLER_OPERATION_FAILED_RESOURCES_RETAINED")


def lifecycle_window(now=None):
    now = now or datetime.now(timezone.utc)
    require(now.tzinfo is not None and now.utcoffset() == timedelta(0), "UTC_CLOCK_REQUIRED")
    boundary = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    remaining = (boundary - now).total_seconds()
    require(remaining > RUN_TIMEOUT + CLEANUP_TIMEOUT + DAY_MARGIN, "DAILY_COUNTER_WINDOW_TOO_SHORT")
    return {"checkedAt": now.isoformat(), "nextUtcDay": boundary.isoformat(), "remainingSeconds": round(remaining, 3),
            "runDeadlineSeconds": RUN_TIMEOUT, "cleanupDeadlineSeconds": CLEANUP_TIMEOUT, "marginSeconds": DAY_MARGIN}


def public_acceptance(value):
    require(value.get("status") == "PASS_SYNTHETIC_RUNTIME_LIFECYCLE_ONLY" and value.get("project") == PROJECT
            and value.get("foreignResourcesChanged") == 0 and "privateCredentials" not in value,
            "LIFECYCLE_RESULT_NOT_ACCEPTED")
    steps = value["steps"]
    require(len(steps) == 11 and all(s["status"] == "PASS" for s in steps), "LIFECYCLE_MATRIX_INCOMPLETE")
    uptime = next(s["evidence"] for s in steps if s["name"] == "continuous_uptime_and_live_generation")
    require(uptime["observedSeconds"] >= SECONDS and uptime["sameStartedAt"] is True
            and uptime["postDeadlineGeneration"]["realModelExecution"] is False, "ORDINARY_UPTIME_NOT_PROVEN")
    accepted = value["accepted"]
    require(value["perUserImages"] == {"owner": 9, "other": 0} and len(accepted["product"]["jobs"]) == 9
            and len(accepted["database"]["charges"]) == 9, "NINE_JOB_RESULT_NOT_PROVEN")
    return {"status": value["status"], "steps": [{k: s[k] for k in ("name", "status", "seconds")} for s in steps],
            "uptime": {k: uptime[k] for k in ("observedSeconds", "samples", "sameStartedAt", "postDeadlineGeneration")},
            "perUserImages": value["perUserImages"], "topology": accepted["topology"], "database": accepted["database"],
            "productSha256": hashlib.sha256(json.dumps(accepted["product"], sort_keys=True).encode()).hexdigest(),
            "planSha256": value["planSha256"], "activeReceiptSha256": value["activeReceiptSha256"],
            "ownerReceiptSha256": value["ownerReceiptSha256"], "foreignResourcesChanged": 0,
            "credentialsUploaded": False, "sessionIdentifiersUploaded": False, "cookiesUploaded": False}


def receiver(args, report):
    report["stage"] = "transfer_integrity"
    producer = transfer(args, report["runner"], report["engine"])
    report["producerReceiptSha256"] = linux.digest(args.transfer / "producer.json")
    report["producerIdentity"] = {k: producer[k] for k in ("runner", "engine", "before")}
    for label in ("A", "B"):
        for suffix in (".zip", ".receipt.json"):
            name = "release-" + label + suffix
            shutil.copyfile(args.transfer / name, args.root / name)
    plan = make_plan(args, producer, report["engine"])
    linux.write_json(args.root / "plan.json", plan); plan_pin = linux.digest(args.root / "plan.json")
    report["stage"] = "daily_counter_window"
    report["lifecycleWindow"] = lifecycle_window()
    report["stage"] = "ordinary_nine_job_lifecycle"
    controller(args, "run", plan_pin)
    path = args.root / "runtime-acceptance.json"; acceptance = read(path)
    report["acceptance"] = public_acceptance(acceptance)
    require(not (args.root / "private").exists(), "CREDENTIAL_ARTIFACT_FORBIDDEN")
    report["acceptanceReceiptSha256"] = linux.digest(path)
    report["stage"] = "explicit_owned_cleanup"
    controller(args, "cleanup", plan_pin, report["acceptanceReceiptSha256"])
    cleanup = read(args.root / "cleanup.json")
    require(cleanup.get("status") == "PASS_OWNED_SYNTHETIC_CLEANUP" and cleanup.get("foreignResourcesChanged") == 0,
            "OWNED_CLEANUP_NOT_PROVEN")
    report["cleanup"] = {k: cleanup[k] for k in ("status", "containersRemoved", "removedVolumes", "claimsRemoved", "foreignResourcesChanged")}
    report["after"] = linux.inventory()
    require(not report["after"]["containers"] and not report["after"]["volumes"], "RECEIVER_RUNTIME_RESOURCES_REMAIN")
    report["imagesRetainedOnEphemeralRunner"] = len(report["after"]["images"])
    report["status"] = PASS


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("producer", "receiver"))
    for name in ("candidate", "tooling", "source-b", "root"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--source-a", type=Path); parser.add_argument("--transfer", type=Path); parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    report = {"status": "FAIL", "contract": CONTRACT, "profile": "synthetic-runtime", "toolingSha": TOOLING,
              "stage": "preflight", "startedAt": datetime.now(timezone.utc).isoformat(), "productionAuthorized": False,
              "realModelExecution": False, "automaticCleanupOnFailure": False}
    created = False
    try:
        require(not args.root.exists(), "RUN_ROOT_NOT_FRESH")
        args.root.mkdir(parents=True, mode=0o700); created = True
        report["runner"] = linux.runner_metadata(args.action)
        sources(args, report["runner"])
        report["engine"] = linux.engine_metadata(report["runner"]["bootFingerprint"])
        report["before"] = linux.inventory()
        linux.fresh_engine(report["before"], args.action)
        if args.action == "producer":
            require(args.source_a is not None, "SOURCE_A_REQUIRED")
            data = support(args)
            report.update(moduleHashes=data["moduleHashes"], httpClientSha256=data["httpClientSha256"], controllerHashes=CONTROLLERS, releases={})
            for label in ("A", "B"):
                report["releases"][label] = build_release(args, label, report)
            require(not linux.inventory()["containers"] and not linux.inventory()["volumes"], "PRODUCER_RUNTIME_RESOURCES_REMAIN")
            report["status"] = "PASS_ORDINARY_PRODUCER_ONLY"
        else:
            require(args.transfer is not None and args.receipt is not None, "RECEIVER_PATHS_REQUIRED")
            receiver(args, report)
        sources(args, report["runner"])
    except Exception as error:
        report.update(status="FAIL", reason=safe(error))
        for name, key in (("runtime-acceptance.json", "controllerFailure"), ("cleanup.json", "cleanupFailure")):
            path = args.root / name
            if args.action == "receiver" and path.is_file():
                value = read(path)
                report[key] = {field: value[field] for field in ("status", "stage", "reason", "removedVolumes") if field in value}
                report[key]["steps"] = [{field: step[field] for field in ("name", "status", "seconds") if field in step}
                                        for step in value.get("steps", [])]
    finally:
        report["finishedAt"] = datetime.now(timezone.utc).isoformat()
        if created:
            path = args.root / "producer.json" if args.action == "producer" else (args.receipt or args.root / "receiver.json")
            linux.write_json(path, report)
    print(json.dumps({"status": report["status"], "reason": report.get("reason")}))
    return 0 if report["status"].startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
