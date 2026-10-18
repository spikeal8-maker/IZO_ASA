"""Finite D3 CI entrypoint on a new disposable VM using accepted D1/D2 images.

Full remains an independent exact-version CI acceptance gate. No cross-workflow
polling, credentials, registry upload, image rebuild, or production target exists.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import time

from tools.docker_clean_install import host_admission
from tools.docker_d3_images import (export_images, load_images, read_installations, read_json,
                                    runtime_sources, save_private)
from tools.docker_d3_orchestration import BudgetExpired, admit_attempts, rehearse_d3, wallclock
from tools.docker_shadow import Shadow
from tools.docker_shadow_product import require


def owned_input(path, temporary, output):
    require(path is not None, "D3_INPUT_DIRECTORY_REQUIRED")
    path, temporary, output = Path(path).absolute(), Path(temporary).resolve(), Path(output).resolve()
    require(path == path.resolve() and path.is_relative_to(temporary) and path != temporary and path.is_dir()
            and not path.resolve().is_relative_to(output) and not output.is_relative_to(path.resolve()),
            "D3_INPUT_DIRECTORY_NOT_OWNED")
    current = path
    while current != temporary:
        require(not current.is_symlink(), "D3_INPUT_SYMLINK_REJECTED")
        current = current.parent
    return path


def seed_host(source_sha, host):
    bootstrap = Shadow("izo-asa-shadow-d3-admission", source_sha)
    bootstrap.source_guard()
    info = json.loads(bootstrap.run(["docker", "--context", "default", "info", "--format", "{{json .}}"], timeout=15))
    require(info.get("OSType") == "linux", "D3_LINUX_DOCKER_REQUIRED")
    host.update(engineId=info["ID"], docker=info["ServerVersion"], cpuCount=info["NCPU"], dockerMemoryBytes=info["MemTotal"])
    for key in ("runId", "attempt"):
        require(isinstance(host[key], str) and re.fullmatch(r"[1-9][0-9]{0,14}", host[key]), "D3_CI_IDENTITY_INVALID")
    seed = Shadow(f"izo-asa-shadow-d3-{host['runId']}-{host['attempt']}", source_sha, fixture=True,
        executor_context="default", engine_id=host["engineId"], machine_sha256=host["machineIdentitySha256"])
    seed.executor.verify()
    return seed


def run_transferred(seed, host, args, evidence, *, admission_only=False):
    directories = [owned_input(path, os.environ["RUNNER_TEMP"], args.evidence_dir)
                   for path in (args.linux_1_dir, args.linux_2_dir, args.images_dir)]
    require(len({path.resolve() for path in directories}) == 3, "D3_INPUT_DIRECTORIES_REUSED")
    reports, proofs = [], []
    for replica, directory in enumerate(directories[:2], 1):
        rows, hashes = read_installations(directory, args.source_sha, args.base_sha, host["runId"], host["attempt"], replica)
        reports.extend(rows)
        proofs.append(hashes)
    manifest = read_json(directories[2] / "handoff.json", 64 * 1024)
    require(isinstance(manifest, dict) and type(manifest.get("version")) is int and manifest["version"] == 1
            and manifest.get("status") == "PASS" and manifest.get("evidenceClass") == "EXACT_TESTED_IMAGE_TRANSFER"
            and manifest.get("repository") == "spikeal8-maker/IZO_ASA" and manifest.get("sourceSha") == args.source_sha
            and manifest.get("baseSha") == args.base_sha and manifest.get("runId") == host["runId"]
            and manifest.get("attempt") == host["attempt"] and manifest.get("replica") == 1
            and manifest.get("installReceipts") == proofs[0]
            and manifest.get("selectedProject") == reports[2]["project"], "D3_HANDOFF_MANIFEST_NOT_CURRENT")
    images = admit_attempts(reports, args.source_sha, manifest["selectedProject"])
    require(all(host["bootIdentitySha256"] != row["host"]["bootIdentitySha256"]
                and host["runnerName"] != row["host"]["runnerName"] for row in reports), "D3_NEW_VM_REQUIRED")
    evidence["D1D2Admission"] = {"status": "PASS", "sourceSha": args.source_sha,
        "installations": 6, "D1Assertions": 48, "D2CasesPerInstallation": 6, "receiptDigests": proofs,
        "priorAggregateStatus": [row["status"] for row in reports], "promotedPartial": False}
    save_private(args.evidence_dir / "entrypoint.json", evidence)
    if admission_only:
        evidence.update(status="NOT_RUN", admissionOnly=True)
        return 0
    evidence["imageHandoff"] = load_images(seed, directories[2], manifest, images, wallclock=wallclock)
    evidence["runtimeSources"] = runtime_sources(seed.root)
    save_private(args.evidence_dir / "entrypoint.json", evidence)
    result = rehearse_d3(seed, args.evidence_dir / "runtime", attempts=reports,
                        selected_project=manifest["selectedProject"])
    require(runtime_sources(seed.root) == evidence["runtimeSources"], "D3_RUNTIME_SOURCE_CHANGED")
    seed.source_guard()
    evidence.update(status=result["status"], controlledScenarios=result["controlledScenarios"],
                    runtimeReceipt="runtime/receipt.json", remainingAcceptance=result["remainingAcceptance"])
    # A controlled protocol PASS cannot satisfy live-model or operator-dependent acceptance.
    return 0 if result["status"] == "PASS" else 2 if result["status"] == "PARTIAL" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "admit", "run"))
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--install-dir", type=Path)
    parser.add_argument("--linux-1-dir", type=Path)
    parser.add_argument("--linux-2-dir", type=Path)
    parser.add_argument("--images-dir", type=Path)
    args = parser.parse_args(argv)
    evidence, admitted, result = {"status": "FAIL", "sourceSha": args.source_sha, "action": args.action}, False, 1
    started = time.monotonic()
    try:
        host = host_admission(args.source_sha, args.base_sha, args.evidence_dir)
        args.evidence_dir.mkdir(mode=0o700)
        admitted = True
        evidence["host"] = host
        seed = seed_host(args.source_sha, host)
        if args.action == "export":
            directory = owned_input(args.install_dir, os.environ["RUNNER_TEMP"], args.evidence_dir)
            reports, proofs = read_installations(directory, args.source_sha, args.base_sha, host["runId"], host["attempt"], 1)
            evidence["transfer"] = export_images(seed, args.evidence_dir, reports, proofs, args.base_sha, wallclock=wallclock)
            evidence["status"], result = "PASS", 0
        else:
            result = run_transferred(seed, host, args, evidence, admission_only=args.action == "admit")
    except (KeyboardInterrupt, BudgetExpired):
        evidence.update(status="FAIL", errorCode="D3_CALLER_INTERRUPTED_OR_DEADLINE")
        result = 1
    except Exception:
        evidence.update(status="FAIL", errorCode="D3_CALLER_ADMISSION_OR_RUNTIME_FAILED")
        result = 1
    finally:
        evidence["seconds"] = round(time.monotonic() - started, 3)
        if admitted:
            save_private(args.evidence_dir / "entrypoint.json", evidence)
    print(json.dumps({"status": evidence["status"], "action": args.action, "sourceSha": args.source_sha,
                      "errorCode": evidence.get("errorCode")}))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
