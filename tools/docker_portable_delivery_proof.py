"""One classic-Linux export and a fresh Linux import; not product lifecycle acceptance."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import zipfile

import docker_linux_bundle_build as common

sys.dont_write_bytecode = True
CONTRACT = "DOCKER-PORTABLE-DELIVERY-PROOF-001"
SOURCE = "7faf354ef1e9438adae1d9a4bbf2346b6e843bbe"
TOOLING = "8667c47544b3048aeaee032f9f8f10066a656755"
COMMON = "2192a7aef412442850e25b73945c2c8e773859844ca77bcb5849d681ae2e6913"
PROJECT, PORTS = "izo-asa-bundle-portable01", {"web": 48784, "api": 48785}
BOOTSTRAP = ("docker_test_bundle_format.py", "docker_test_bundle_images.py")
MODULES = (*BOOTSTRAP, "docker_test_bundle_runtime.py")
require = common.require


def read(path):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 4 * 1024**2, "RECEIPT_INPUT_INVALID")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    require(type(value) is dict, "RECEIPT_OBJECT_REQUIRED")
    return value


def guards(args, runner):
    require(runner["head"] != SOURCE, "WORKFLOW_HEAD_IS_NOT_APPLICATION_HEAD")
    require(runner["head"] != TOOLING, "WORKFLOW_HEAD_IS_NOT_TOOLING_HEAD")
    checkouts = [(args.driver, runner["head"]), (args.tooling, TOOLING)]
    if args.action == "producer":
        require(args.source is not None and args.acceptance is not None, "SOURCE_CHECKOUTS_REQUIRED")
        checkouts += [(args.source, SOURCE), (args.acceptance, SOURCE)]
    paths = [args.root, *[path for path, _ in checkouts]] + ([args.transfer] if args.transfer else [])
    require(all(p.is_absolute() and ".." not in p.parts and "$" not in str(p)
                and not any(q.is_symlink() for q in (p, *p.parents)) for p in paths), "UNSAFE_PATH")
    require(all(not a.is_relative_to(b) and not b.is_relative_to(a)
                for i, a in enumerate(paths) for b in paths[i + 1:]), "OVERLAPPING_PATHS")
    for path, sha in checkouts:
        common.source_guard(path, sha)
    helper = args.driver / "tools/docker_linux_bundle_build.py"
    require(Path(common.__file__).resolve() == helper.resolve()
            and hashlib.sha256(helper.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == COMMON,
            "COMMON_HELPER_CHANGED")
    require(Path(__file__).resolve() == (args.driver / "tools/docker_portable_delivery_proof.py").resolve()
            and platform.python_version() == (args.driver / ".python-version").read_text().strip(), "PROOF_CHECKOUT_CHANGED")


def image_store():
    value = json.loads(common.run(["docker", "--context", "default", "info", "--format",
                                  '{"driver":{{json .Driver}},"driverStatus":{{json .DriverStatus}}}']))
    rows = value.get("driverStatus")
    require(type(rows) is list and all(type(row) is list and len(row) == 2
            and all(type(cell) is str for cell in row) for row in rows), "IMAGE_STORE_EVIDENCE_INVALID")
    containerd = ["driver-type", "io.containerd.snapshotter.v1"] in rows
    require(containerd or value.get("driver") == "overlay2", "IMAGE_STORE_UNSUPPORTED")
    return {**value, "kind": "containerd" if containerd else "classic"}


def context_proof(root):
    value = read(root / "context.json")
    require(value.get("contract") == "DOCKER-CANONICAL-CANDIDATE-002"
            and value.get("status") == "PASS_CONTEXT_EXPORT_ONLY" and value.get("sourceSha") == SOURCE
            and value.get("sourceDirty") is False, "CONTEXT_PROOF_CHANGED")
    return {"receipt": value, "receiptSha256": common.digest(root / "context.json")}


def release(root, record, tooling):
    archive = root / "release.zip"; receipt = read(root / "release.receipt.json")
    require(record["receiptSha256"] == common.digest(root / "release.receipt.json") and record["receipt"] == receipt
            and receipt.get("status") == "TEST_BUNDLE_BUILT" and receipt.get("source_sha") == SOURCE
            and receipt.get("tooling_sha") == TOOLING and receipt.get("project") == PROJECT
            and receipt.get("images_embedded") is True and receipt.get("production_authorized") is False
            and receipt.get("archive_bytes") == archive.stat().st_size
            and receipt.get("archive_sha256") == common.digest(archive), "TRANSFER_RELEASE_CHANGED")
    with zipfile.ZipFile(archive) as bundle:
        require(bundle.namelist().count("bundle.json") == 1 and bundle.getinfo("bundle.json").file_size <= 2 * 1024**2,
                "BUNDLE_METADATA_INVALID")
        for name in MODULES:
            expected = tooling / "tools" / name
            require(bundle.namelist().count(name) == 1 and bundle.getinfo(name).file_size == expected.stat().st_size
                    and hashlib.sha256(bundle.read(name)).hexdigest() == common.digest(expected), "EMBEDDED_TOOLING_CHANGED")
        body = bundle.read("bundle.json")
    value = json.loads(body)
    require(hashlib.sha256(body).hexdigest() == receipt["manifest_sha256"] and value.get("format") == 2
            and value.get("profile") == "synthetic-runtime" and value.get("source_sha") == SOURCE
            and value.get("tooling_sha") == TOOLING and value.get("project") == PROJECT and value.get("ports") == PORTS
            and value.get("production_authorized") is False and value.get("model_execution") is False
            and value.get("image_identity", {}).get("version") == 1, "PORTABLE_MANIFEST_REQUIRED")
    return value


def producer(args, report):
    require(report["imageStore"]["kind"] == "classic", "CLASSIC_PRODUCER_REQUIRED")
    report["stage"] = "canonical-context"
    paths = {"root": args.source / ".dockerignore", **{role: args.source / "ops/docker/dev" /
             ("Dockerfile." + role + ".dockerignore") for role in ("web", "guard")}}
    pins = {role: common.digest(path) for role, path in paths.items()}
    common.source_guard(args.source, SOURCE)
    common.run([sys.executable, "-B", "-m", "tools.docker_canonical_context_probe", "--source", str(args.source),
                "--context", "default", "--receipt", str(args.root / "context.json")], cwd=args.acceptance, timeout=300)
    common.source_guard(args.source, SOURCE); common.source_guard(args.acceptance, SOURCE)
    report["contextProof"] = context_proof(args.root)
    require(report["contextProof"]["receipt"].get("ignoreSha256") == pins
            and {role: common.digest(path) for role, path in paths.items()} == pins, "CONTEXT_IGNORE_CHANGED")
    report["stage"] = "compose-validation"; report["dockerfiles"] = common.pinned_dockerfiles(args.source)
    env = {**common.environment(), "IZO_SOURCE_SHA": SOURCE, "IZO_COMPOSE_PROJECT": PROJECT,
           "IZO_SHADOW_WEB_PORT": str(PORTS["web"]), "IZO_SHADOW_API_PORT": str(PORTS["api"])}
    command = ["docker", "--context", "default", "compose", "--env-file", os.devnull, "--project-name", PROJECT]
    for name in ("compose.yml", "compose.shadow.yml"):
        command += ["-f", str(args.source / "ops/docker/dev" / name)]
    rendered = common.run(command + ["config", "--format", "json"], env=env)
    require(set(json.loads(rendered).get("services", {})) == {"backend", "web", "guard"}, "ORDINARY_COMPOSE_REQUIRED")
    report["composeSha256"] = hashlib.sha256(rendered.encode()).hexdigest(); report["stage"] = "image-build"
    common.run(command + ["build", "--no-cache", "guard", "backend", "web"], env=env, timeout=1800)
    report["stage"] = "bundle-build"
    built = subprocess.run([sys.executable, "-B", "-m", "tools.docker_test_bundle", "build", "--source", str(args.source),
                "--sha", SOURCE, "--project", PROJECT, "--web-port", str(PORTS["web"]), "--api-port", str(PORTS["api"]),
                "--context", "default", "--output", str(args.root / "release.zip"), "--profile", "synthetic-runtime"],
                cwd=args.tooling, env=common.environment(), capture_output=True, text=True, encoding="utf-8", timeout=600, check=False)
    require(len(built.stdout) <= 1024**2, "BUILDER_OUTPUT_TOO_LARGE")
    result = json.loads(built.stdout)
    require(type(result) is dict and re.fullmatch(r"[A-Z][A-Z0-9_]{1,100}", result.get("status", ""))
            and ("reason" not in result or re.fullmatch(r"[A-Z][A-Z0-9_]{1,100}", result["reason"])), "BUILDER_RESULT_INVALID")
    report["bundleBuildResult"] = result
    require(built.returncode == 0 and result["status"] == "TEST_BUNDLE_BUILT", "BUNDLE_BUILD_FAILED")
    report["stage"] = "producer-artifact-validation"
    report["release"] = {"receipt": read(args.root / "release.receipt.json"),
                         "receiptSha256": common.digest(args.root / "release.receipt.json")}
    report["imageIdentity"] = release(args.root, report["release"], args.tooling)["image_identity"]
    report["moduleHashes"] = {name: common.digest(args.tooling / "tools" / name) for name in MODULES}
    for name in BOOTSTRAP:
        shutil.copyfile(args.tooling / "tools" / name, args.root / name)
    report["bootstrap"] = {name: common.digest(args.root / name) for name in BOOTSTRAP}
    require(not common.inventory()["containers"] and not common.inventory()["volumes"], "PRODUCER_RESOURCES_REMAIN")
    report["status"] = "PASS_PORTABLE_PRODUCER_ONLY"


def transfer(args, report):
    pin = os.environ.get("IZO_PRODUCER_RECEIPT_SHA256", "")
    require(re.fullmatch(r"[0-9a-f]{64}", pin) and common.digest(args.transfer / "producer.json") == pin,
            "PRODUCER_RECEIPT_PIN_MISMATCH")
    prior = read(args.transfer / "producer.json"); runner = report["runner"]
    require(prior.get("contract") == CONTRACT and prior.get("status") == "PASS_PORTABLE_PRODUCER_ONLY"
            and prior.get("applicationSha") == prior.get("acceptanceSha") == SOURCE
            and prior.get("workflowSha") == runner["head"] and prior.get("toolingSha") == TOOLING
            and prior.get("before") == {"images": [], "containers": [], "volumes": []}
            and prior.get("imageStore", {}).get("kind") == "classic", "PRODUCER_CONTRACT_CHANGED")
    require(all(prior["runner"][key] == runner[key] for key in ("head", "runId", "attempt"))
            and prior["runner"]["job"] == "producer" and runner["job"] == "receiver", "SEPARATE_JOB_REQUIRED")
    require(prior["runner"]["bootFingerprint"] != runner["bootFingerprint"], "DISTINCT_BOOT_REQUIRED")
    for value in (prior, report):
        require(value["engine"]["engineInstanceFingerprint"] == common.engine_instance_fingerprint(
            value["engine"], value["runner"]["bootFingerprint"]), "ENGINE_EVIDENCE_CHANGED")
    require(prior["engine"]["engineInstanceFingerprint"] != report["engine"]["engineInstanceFingerprint"], "DISTINCT_ENGINE_REQUIRED")
    require(prior["contextProof"] == context_proof(args.transfer) and prior["bootstrap"] ==
            {name: common.digest(args.tooling / "tools" / name) for name in BOOTSTRAP} ==
            {name: common.digest(args.transfer / name) for name in BOOTSTRAP} and prior["moduleHashes"] ==
            {name: common.digest(args.tooling / "tools" / name) for name in MODULES}, "SUPPORT_TRANSFER_CHANGED")
    manifest = release(args.transfer, prior["release"], args.tooling)
    require(prior["imageIdentity"] == manifest["image_identity"], "IMAGE_IDENTITY_CHANGED")
    report.update(producerReceiptSha256=pin, imageIdentity=prior["imageIdentity"], release=prior["release"], moduleHashes=prior["moduleHashes"])
    return manifest


def receiver(args, report):
    report["stage"] = "transfer-validation"
    manifest = transfer(args, report); record = report["release"]["receipt"]
    incoming, state = args.root / "incoming", args.root / "installed"; report["stage"] = "extract"
    common.run([sys.executable, "-B", "-m", "tools.docker_test_bundle", "extract", "--archive", str(args.transfer / "release.zip"),
                "--sha256", record["archive_sha256"], "--destination", str(incoming)], cwd=args.tooling, timeout=300)
    command = [sys.executable, "-B", str(incoming / "docker_test_bundle_runtime.py"), "install", "--test-only",
               "--context", "default", "--state-dir", str(state), "--manifest-sha256", record["manifest_sha256"]]
    report["installs"] = []
    for _ in range(2):
        report["stage"] = "install" if not report["installs"] else "repeat-install"
        process = subprocess.run(command, env=common.environment(), capture_output=True, text=True, timeout=300, check=False)
        require(len(process.stdout) <= 1024**2, "INSTALLER_OUTPUT_TOO_LARGE")
        result = json.loads(process.stdout); report["installs"].append(result)
        require(process.returncode == 0 and result.get("status") == "TEST_RUNTIME_VERIFIED"
                and result.get("source_sha") == SOURCE and result.get("profile") == "synthetic-runtime"
                and result.get("engine") == report["engine"]["fingerprint"]
                and result.get("manifest_sha256") == record["manifest_sha256"] and result.get("image_identity_version") == 1
                and set(result.get("resolved_images", {})) == {"backend", "web", "guard"}, "PORTABLE_INSTALL_FAILED")
        owner = common.digest(state / "owner.json")
        if len(report["installs"]) == 1: report["ownerReceiptSha256"] = owner
        require(owner == report["ownerReceiptSha256"] and result == report["installs"][0], "REPEAT_INSTALLATION_CHANGED")
    report["stage"] = "receiver-evidence"
    ids = common.run(["docker", "--context", "default", "ps", "-q", "--no-trunc", "--filter",
                      "label=com.docker.compose.project=" + PROJECT]).split()
    rows = json.loads(common.run(["docker", "--context", "default", "inspect", *ids])) if ids else []
    report["containerImages"] = {r["Config"]["Labels"]["com.docker.compose.service"]: r["Image"] for r in rows}
    require(len(rows) == 3 and report["containerImages"] == result["resolved_images"], "CONTAINER_IMAGE_CHANGED")
    after = common.inventory()
    require(set(after["containers"]) == set(ids) and set(after["volumes"]) ==
            {PROJECT + suffix for suffix in ("_sqlite-data", "_media-data", "-installation")}, "RECEIVER_FOREIGN_RESOURCE_CHANGED")
    require(release(args.transfer, report["release"], args.tooling) == manifest, "TRANSFER_CHANGED_AFTER_INSTALL")
    report.update(status="PASS_PORTABLE_IMAGE_IDENTITY_LINUX_ONLY", after=after)


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("action", choices=("producer", "receiver"))
    for name in ("driver", "tooling", "root", "source", "acceptance", "transfer"):
        parser.add_argument("--" + name, type=Path, required=name in ("driver", "tooling", "root"))
    args = parser.parse_args(); report = {"status": "FAIL", "contract": CONTRACT, "applicationSha": SOURCE, "acceptanceSha": SOURCE,
        "startedAt": datetime.now(timezone.utc).isoformat(), "stage": "preflight",
        "productionAuthorized": False, "realModelExecution": False, "productLifecycleProven": False, "explicitCleanupPerformed": False}
    created = False
    try:
        report["runner"] = common.runner_metadata(args.action); guards(args, report["runner"])
        require(not args.root.exists() and (args.action != "receiver" or args.transfer is not None), "FRESH_ROOT_AND_TRANSFER_REQUIRED")
        args.root.mkdir(parents=True, mode=0o700); created = True
        report.update(workflowSha=report["runner"]["head"], toolingSha=TOOLING, stage="fresh-engine")
        report["engine"] = common.engine_metadata(report["runner"]["bootFingerprint"])
        report["before"] = common.inventory(); common.fresh_engine(report["before"], args.action)
        report["stage"] = "image-store"; report["imageStore"] = image_store()
        (producer if args.action == "producer" else receiver)(args, report)
        report["stage"] = "post-source-validation"; guards(args, report["runner"]); report["stage"] = "complete"
    except Exception as error:
        reason = str(error); report.update(status="FAIL", reason=reason if re.fullmatch(r"[A-Z][A-Z0-9_]{1,100}", reason) else type(error).__name__)
    finally:
        report["finishedAt"] = datetime.now(timezone.utc).isoformat()
        if created: common.write_json(args.root / (args.action + ".json"), report)
    print(json.dumps({key: report.get(key) for key in ("status", "reason")}))
    return 0 if report["status"].startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
