"""Real fresh Linux receiver acceptance; calls the existing TEST installer only."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    from tools.docker_linux_bundle_build import (CONTRACT, PORTS, PROJECT, SOURCES, TOOLING, ProofError,
        digest, engine_instance_fingerprint, engine_metadata, environment, fresh_engine, inventory, require, run,
        runner_metadata, source_guard, write_json)
except ModuleNotFoundError:
    from docker_linux_bundle_build import (CONTRACT, PORTS, PROJECT, SOURCES, TOOLING, ProofError,
        digest, engine_instance_fingerprint, engine_metadata, environment, fresh_engine, inventory, require, run,
        runner_metadata, source_guard, write_json)

sys.dont_write_bytecode = True


def load_support(tooling: Path, source: Path):
    sys.path.insert(0, str(tooling))
    fmt = importlib.import_module("tools.docker_test_bundle_format")
    runtime = importlib.import_module("tools.docker_test_bundle_runtime")
    require(all(Path(module.__file__).resolve().is_relative_to(tooling.resolve())
                for module in (fmt, runtime)), "PINNED_TOOL_MODULE_REQUIRED")
    spec = importlib.util.spec_from_file_location("linux_bounded_http", source / "tools/docker_shadow_product.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return fmt, runtime, module


def installer_environment(directory: Path) -> dict:
    directory.mkdir()
    docker = shutil.which("docker")
    require(docker is not None, "DOCKER_CLI_MISSING")
    for name, target in (("python", sys.executable), ("python3", sys.executable), ("docker", docker)):
        (directory / name).symlink_to(Path(target).resolve())
    value = {**environment(), "PATH": str(directory)}
    require(all(shutil.which(name, path=value["PATH"]) is None for name in ("git", "node", "npm")),
            "INSTALLER_FORBIDDEN_TOOL_REACHABLE")
    proof = run([sys.executable, "-B", "-c", "import shutil,json; print(json.dumps({k:bool(shutil.which(k)) for k in ('python','docker','git','node','npm')}))"], env=value)
    require(json.loads(proof) == {"python": True, "docker": True, "git": False, "node": False, "npm": False},
            "INSTALLER_PATH_PROOF_FAILED")
    run(["docker", "--context", "default", "compose", "version", "--short"], env=value)
    return value


def validate_transfer(root: Path, expected: str, runner: dict, engine: dict) -> dict:
    require(re.fullmatch(r"[0-9a-f]{64}", expected or "") is not None
            and digest(root / "producer.json") == expected, "PRODUCER_RECEIPT_PIN_MISMATCH")
    producer = json.loads((root / "producer.json").read_text(encoding="utf-8"))
    require(producer.get("contract") == CONTRACT
            and producer.get("before") == {"images": [], "containers": [], "volumes": []},
            "PRODUCER_FRESH_ENGINE_EVIDENCE_REQUIRED")
    prior = producer["runner"]
    require(producer["status"] == "PASS_TEST_PRODUCER_ONLY" and producer["toolingSha"] == TOOLING
            and all(prior[k] == runner[k] for k in ("head", "runId", "attempt"))
            and prior["job"] == "producer" and runner["job"] == "receiver", "SEPARATE_PRODUCER_REQUIRED")
    require(all(type(item.get("bootFingerprint")) is str
                and re.fullmatch(r"[0-9a-f]{64}", item["bootFingerprint"]) is not None
                for item in (prior, runner)) and prior["bootFingerprint"] != runner["bootFingerprint"],
            "DISTINCT_LINUX_BOOT_REQUIRED")
    for value, host in ((producer["engine"], prior), (engine, runner)):
        expected_instance = engine_instance_fingerprint(value, host["bootFingerprint"])
        require(value.get("engineInstanceFingerprint") == expected_instance, "ENGINE_INSTANCE_FINGERPRINT_MISMATCH")
    require(producer["engine"]["engineInstanceFingerprint"] != engine["engineInstanceFingerprint"],
            "DISTINCT_ENGINE_INSTANCE_REQUIRED")
    for label, sha in SOURCES.items():
        path = root / ("release-" + label + ".receipt.json")
        record = producer["releases"][label]
        receipt = json.loads(path.read_text(encoding="utf-8"))
        require(record["receipt"] == receipt and record["receiptSha256"] == digest(path)
                and receipt["source_sha"] == sha and receipt["tooling_sha"] == TOOLING
                and receipt["project"] == PROJECT and receipt["images_embedded"] is True
                and receipt["archive_sha256"] == digest(root / ("release-" + label + ".zip")),
                "TRANSFER_IDENTITY_MISMATCH")
    return producer


def resource_identity(resources: dict) -> dict:
    """Exclude healthcheck timestamps while retaining mutable lifecycle identity."""
    return {
        "containers": {v["Id"]: {"image": v["Image"], "labels": v["Config"]["Labels"],
            "running": v["State"]["Running"], "started": v["State"]["StartedAt"]}
            for v in resources["containers"]},
        "volumes": {v["Name"]: {k: v.get(k) for k in ("Driver", "Scope", "CreatedAt", "Labels", "Options")}
            for v in resources["volumes"]},
        "networks": {v["Id"]: {"name": v["Name"], "labels": v.get("Labels")}
            for v in resources["networks"]},
    }


class Receiver:
    def __init__(self, args, report: dict, support):
        self.args, self.report = args, report
        self.fmt, self.runtime, self.http = support
        self.docker = self.runtime.Docker("default")
        self.state = args.work / "installed"
        self.child_env = installer_environment(args.work / "installer-bin")
        self.receipts = {k: report["producer"]["releases"][k]["receipt"] for k in SOURCES}
        self.extracted = {k: args.work / ("unpacked " + k + " Тест") for k in SOURCES}
        self.manifests, self.active = {}, None
        self.clients = [self.http.HttpClient("http://127.0.0.1:" + str(PORTS["web"])) for _ in range(3)]
        self.images, self.jobs, self.saved, self.baseline = [], [], None, None
        self.cleanup_expected = {}

    def step(self, name: str, operation, *, negative: bool = False):
        rows = self.report["negativeCases" if negative else "steps"]
        self.report["stage"] = name
        row = {"name": name, "status": "RUNNING"}; rows.append(row)
        write_json(self.args.receipt, self.report)
        started = time.monotonic()
        try:
            row["evidence"] = operation()
            row["status"] = "PASS"
            print("PASS " + name, flush=True)
        except Exception:
            row["status"] = "FAIL"
            raise
        finally:
            row["seconds"] = round(time.monotonic() - started, 3)
            write_json(self.args.receipt, self.report)

    def unpack(self, label: str) -> dict:
        r = self.receipts[label]
        self.fmt.extract(self.args.transfer / ("release-" + label + ".zip"), r["archive_sha256"], self.extracted[label])
        m = self.fmt.verify(self.extracted[label], r["manifest_sha256"])
        require(m["source_sha"] == SOURCES[label] and m["tooling_sha"] == TOOLING
                and m["ports"] == PORTS and m["project"] == PROJECT
                and not (self.extracted[label] / ".git").exists(), "EXTRACTED_IDENTITY_INVALID")
        self.manifests[label] = m
        return {"sourceSha": m["source_sha"], "manifestSha256": r["manifest_sha256"],
                "archiveSha256": r["archive_sha256"], "files": len(m["files"]), "gitDirectory": False}

    def invoke(self, label: str, *, update=False, installed=False, pin=None, state=None):
        r = self.receipts[label]
        root = self.state / "releases" / r["manifest_sha256"] if installed else self.extracted[label]
        args = [sys.executable, "-B", str(root / "docker_test_bundle_runtime.py"), "install",
                "--manifest-sha256", pin or r["manifest_sha256"], "--context", "default",
                "--state-dir", str(state or self.state), "--test-only"]
        if update:
            args.append("--allow-code-update")
        try:
            value = subprocess.run(args, cwd=root, env=self.child_env, capture_output=True,
                                   text=True, encoding="utf-8", timeout=300, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise ProofError("INSTALLER_UNAVAILABLE_OR_TIMEOUT") from None
        require(len(value.stdout) <= 65536 and len(value.stderr) <= 65536, "INSTALLER_OUTPUT_TOO_LARGE")
        try:
            return value.returncode, json.loads(value.stdout)
        except ValueError:
            raise ProofError("INSTALLER_RESPONSE_NOT_JSON") from None

    def install(self, label: str, *, update=False, installed=False) -> dict:
        code, result = self.invoke(label, update=update, installed=installed)
        if code != 0:
            reason = result.get("reason", "INSTALLER_DID_NOT_VERIFY")
            require(isinstance(reason, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{1,100}", reason) is not None,
                    "INSTALLER_DIAGNOSTIC_INVALID")
            raise ProofError(reason)
        require(code == 0 and result.get("status") == "TEST_RUNTIME_VERIFIED"
                and result.get("source_sha") == SOURCES[label]
                and result.get("production_authorized") is False, "INSTALLER_DID_NOT_VERIFY")
        self.active = label
        require(result["volumes"] == self.volumes(), "INSTALLER_VOLUME_RECEIPT_MISMATCH")
        if not self.cleanup_expected:
            self.cleanup_expected = resource_identity(self.resources())["volumes"]
        return {"sourceSha": result["source_sha"], "releaseId": result["release_id"],
                "imageIds": self.manifests[label]["images"], "gitNodeNpmReachable": False}

    def root(self) -> Path:
        return self.state / "releases" / self.receipts[self.active]["manifest_sha256"]

    def resources(self) -> dict:
        return self.runtime.owned_resources(self.docker, self.manifests[self.active or "A"])

    def volumes(self) -> dict:
        owner = json.loads((self.state / "owner.json").read_text())
        return self.runtime.volume_identity(self.resources(), self.manifests[self.active], owner)

    def snapshot(self) -> dict:
        owner, other, guest = self.clients
        data = {"accounts": [], "images": [], "jobs": []}
        guest.request("GET", "/api/me-v2", expected=(401,))
        for client in (owner, other):
            me = client.request("GET", "/api/me-v2")
            history = client.request("GET", "/api/account/token-history-v2?days=365&limit=200")
            data["accounts"].append({"identity": [me["legacy_user_id"], me["internal_user_id"], me["session"]["session_id"]],
                "balance": me["account"]["token_balance"], "used": me["account"]["daily_tokens_used"],
                "history": {"summary": history["summary"], "items": sorted(history["items"], key=lambda x: x["id"])}})
        for image in self.images:
            item = owner.request("GET", "/api/gallery/" + image["id"])
            paths = {item["url"], item.get("thumbnailUrl") or item["url"]}
            media = {p: hashlib.sha256(owner.request("GET", p, binary=True)).hexdigest() for p in paths}
            data["images"].append({"id": item["id"], "favorite": item["isFavorite"], "media": media})
            for client in (other, guest):
                client.request("GET", "/api/gallery/" + item["id"], expected=(401, 403, 404))
                for path in paths:
                    client.request("GET", path, expected=(401, 403, 404))
        for job_id in self.jobs:
            job = owner.request("GET", "/api/jobs/" + job_id)
            require(job["status"] == "completed", "PERSISTENT_JOB_NOT_COMPLETED")
            data["jobs"].append({k: job.get(k) for k in ("id", "status", "resultImageId", "resultUrl")})
            for client in (other, guest):
                client.request("GET", "/api/jobs/" + job_id, expected=(401, 403, 404))
        return data

    def product(self) -> dict:
        owner, other, _ = self.clients
        for client in (owner, other):
            password = secrets.token_urlsafe(32)
            value = client.request("POST", "/api/auth/password/register-v2", {
                "email": "linux-" + uuid.uuid4().hex + "@example.invalid", "password": password,
                "password_repeat": password, "accepted_terms": True, "accepted_privacy": True,
                "accepted_personal_data": True, "platform": "web_desktop"})
            require(value.get("ok") is True and value.get("requires_email_verification") is False,
                    "SYNTHETIC_SIGNUP_FAILED")
        history = owner.request("GET", "/api/account/token-history-v2")
        before, costs = history["summary"]["spentTokens"], 0
        prior_ids = {x["id"] for x in history["items"]}
        for mode in ("text_to_image", "image_to_image"):
            payload = {"mode": mode, "provider": "comfyui", "prompt": "A blue ceramic cup on a plain table",
                       "width": 704, "height": 704, "steps": 4, "seed": 18731}
            if self.images:
                payload["inputImage1"] = self.images[0]["url"]
            job = owner.request("POST", "/api/generate", payload)
            require(type(job.get("tokenCost")) is int and job["tokenCost"] > 0, "SYNTHETIC_JOB_COST_INVALID")
            job_id = self.http.path_id(job["id"]); self.jobs.append(job_id); costs += job["tokenCost"]
            deadline = time.monotonic() + 60
            while True:
                status = owner.request("GET", "/api/jobs/" + job_id)
                if status["status"] == "completed":
                    break
                require(status["status"] not in {"failed", "cancelled"} and time.monotonic() < deadline,
                        "SYNTHETIC_JOB_FAILED_OR_TIMEOUT")
                time.sleep(.2)
            self.images.append(owner.request("GET", "/api/gallery/" + self.http.path_id(status["resultImageId"])))
        history = owner.request("GET", "/api/account/token-history-v2")
        charges = [x for x in history["items"] if x["id"] not in prior_ids and x["spentTokens"] > 0]
        require(history["summary"]["spentTokens"] - before == costs and len(charges) == 2
                and sum(x["spentTokens"] for x in charges) == costs, "SYNTHETIC_LEDGER_MISMATCH")
        owner.request("POST", "/api/gallery/" + self.images[0]["id"] + "/favorite", {"isFavorite": True})
        self.saved, self.baseline = self.snapshot(), self.volumes()
        require(self.saved["accounts"][0]["identity"] != self.saved["accounts"][1]["identity"]
                and self.saved["images"][0]["favorite"] is True, "SYNTHETIC_BASELINE_INVALID")
        return {"syntheticUsers": 2, "completedJobs": 2, "charges": len(charges), "tokenCost": costs,
                "privateMediaIsolation": "PASS", "favorite": "PASS"}

    def persisted(self) -> dict:
        require(self.snapshot() == self.saved, "SYNTHETIC_PERSISTENCE_CHANGED")
        require(self.volumes() == self.baseline, "PERSISTENT_VOLUME_IDENTITY_CHANGED")
        health = self.runtime.health(self.docker, self.root(), self.manifests[self.active])
        return {"dataSha256": hashlib.sha256(json.dumps(self.saved, sort_keys=True).encode()).hexdigest(),
                "volumeIdentity": self.baseline, "releaseId": health["release_id"], "privateAccess": "PASS"}

    def repeat(self, label: str) -> dict:
        ids = {x["Id"] for x in self.resources()["containers"]}
        self.install(label, installed=True)
        require(ids == {x["Id"] for x in self.resources()["containers"]}, "REPEAT_RECREATED_CONTAINERS")
        return {**self.persisted(), "sameContainerIds": True}

    def reconstruct(self) -> dict:
        self.fmt.verify(self.extracted["A"], self.receipts["A"]["manifest_sha256"])
        shutil.rmtree(self.extracted["A"])
        self.docker.compose(self.root(), self.manifests[self.active], "config", "--quiet")
        return {"originalUnpackedRemoved": True, "permanentCompose": "PASS", **self.persisted()}

    def change(self, label: str) -> dict:
        self.install(label, update=True, installed=not self.extracted[label].exists())
        return self.persisted()

    def recreate(self) -> dict:
        self.resources()
        self.docker.compose(self.root(), self.manifests[self.active], "down")
        require(not self.resources()["containers"], "CONTAINERS_NOT_REMOVED")
        self.install("B", installed=True)
        return self.persisted()

    def blocked(self, reason: str, **kwargs) -> dict:
        before = resource_identity(self.resources())
        receipt = (self.state / "active.json").read_bytes()
        code, value = self.invoke("B", installed=True, **kwargs)
        require(code != 0 and value.get("reason") == reason, "NEGATIVE_DID_NOT_BLOCK")
        require(resource_identity(self.resources()) == before and (self.state / "active.json").read_bytes() == receipt,
                "NEGATIVE_MUTATED_RESOURCES_OR_RECEIPT")
        return {"reason": reason, "resourceMutation": False, "activeReceiptChanged": False}

    def corrupt_archive(self) -> dict:
        archive = self.args.work / "corrupt.zip"
        with (self.args.transfer / "release-B.zip").open("rb") as stream:
            content = bytearray(stream.read(4096))
        content[0] ^= 1; archive.write_bytes(content)
        destination = self.args.work / "bad-extract"
        try:
            self.fmt.extract(archive, self.receipts["B"]["archive_sha256"], destination)
        except self.fmt.BundleError as error:
            require(str(error) == "ARCHIVE_PIN_MISMATCH" and not destination.exists(), "CORRUPT_ARCHIVE_GATE_INVALID")
            return {"reason": str(error), "destinationCreated": False}
        raise ProofError("CORRUPT_ARCHIVE_ACCEPTED")

    def copied_state(self) -> dict:
        copied = self.args.work / "copied-state"; copied.mkdir()
        for name in ("owner.json", "active.json"):
            shutil.copyfile(self.state / name, copied / name)
        return self.blocked("INSTALLATION_OWNER_MISMATCH", state=copied)

    def missing_and_drift(self) -> dict:
        self.resources()
        self.docker.compose(self.root(), self.manifests[self.active], "down")
        name = PROJECT + "_worker_ipc"
        before = next(v for v in self.resources()["volumes"] if v["Name"] == name)
        owner = json.loads((self.state / "owner.json").read_text())
        require(before["Labels"]["io.izo.bundle.installation"] == owner["id"]
                and self.volumes() == self.baseline, "NEGATIVE_VOLUME_NOT_OWNED")
        self.docker.run("volume", "rm", name)
        self.cleanup_expected.pop(name)
        missing = self.blocked("PERSISTENT_VOLUME_MISSING")
        labels = {**before["Labels"], "io.izo.bundle.generation": uuid.uuid4().hex}
        self.runtime.claim_volume(self.docker, name, labels, "NEGATIVE_REPLACEMENT_CLAIM_FAILED")
        replacement = resource_identity(self.resources())["volumes"][name]
        require(replacement["Labels"] == labels and replacement["CreatedAt"], "NEGATIVE_REPLACEMENT_IDENTITY_INVALID")
        self.cleanup_expected[name] = replacement
        drift = self.blocked("PERSISTENT_VOLUME_DRIFT")
        return {"missing": missing, "recreatedGeneration": drift, "syntheticIpcOnly": True}

    def cleanup(self) -> dict:
        for client in self.clients:
            client.cookies.clear()
        owner_path = self.state / "owner.json"
        if not owner_path.exists():
            require(not inventory()["containers"] and not inventory()["volumes"], "UNCLAIMED_RESOURCES_REMAIN")
            return {"status": "PASS", "ownedResourcesCreated": False}
        owner = json.loads(owner_path.read_text())
        require(owner["project"] == PROJECT and owner["engine"] == self.report["engine"]["fingerprint"]
                and owner["state"] == hashlib.sha256(str(self.state.absolute()).encode()).hexdigest(), "CLEANUP_OWNER_MISMATCH")
        require(self.docker.run("volume", "inspect", PROJECT + "-operation-lock", optional=True) is None,
                "CLEANUP_REFUSES_STALE_OR_ACTIVE_LOCK")
        resources = self.resources()
        require(resource_identity(resources)["volumes"] == self.cleanup_expected, "CLEANUP_UNEXPECTED_VOLUME_IDENTITY")
        for volume in resources["volumes"]:
            labels = volume["Labels"]
            require(labels.get("io.izo.bundle.installation") == owner["id"]
                    and re.fullmatch(r"[0-9a-f]{32}", labels.get("io.izo.bundle.generation", "")) is not None,
                    "CLEANUP_VOLUME_OWNER_MISMATCH")
        claim = PROJECT + "-installation"
        value = self.docker.run("volume", "inspect", claim, optional=True)
        if value is not None:
            require(json.loads(value)[0]["Labels"] == {"io.izo.bundle": self.fmt.OWNER,
                "io.izo.bundle.installation": owner["id"], "io.izo.bundle.state": owner["state"],
                "io.izo.bundle.engine": owner["engine"]}, "CLEANUP_INSTALLATION_CLAIM_MISMATCH")
        for container in resources["containers"]:
            self.docker.run("rm", "-f", container["Id"])
        for network in resources["networks"]:
            self.docker.run("network", "rm", network["Name"])
        for volume in resources["volumes"]:
            observed = json.loads(self.docker.run("volume", "inspect", volume["Name"]))[0]
            require(observed["Labels"] == volume["Labels"] and observed["CreatedAt"] == volume["CreatedAt"],
                    "CLEANUP_VOLUME_CHANGED")
            self.docker.run("volume", "rm", volume["Name"])
        if value is not None:
            self.docker.run("volume", "rm", claim)
        after = inventory()
        require(not after["containers"] and not after["volumes"], "CLEANUP_RESOURCES_REMAIN")
        return {"status": "PASS", "containersRemoved": len(resources["containers"]),
                "volumesRemoved": len(resources["volumes"]) + int(value is not None),
                "networksRemoved": len(resources["networks"]), "foreignResourcesTouched": False,
                "imagesRetainedOnEphemeralRunner": len(after["images"])}

    def matrix(self):
        for label in ("A", "B"):
            self.step("extract_" + label + "_unicode_path_no_git_directory", lambda k=label: self.unpack(k))
        self.step("install_A_python_docker_only", lambda: self.install("A"))
        self.step("synthetic_users_jobs_ledger_media", self.product)
        self.step("remove_unpack_reconstruct_persistent_config", self.reconstruct)
        self.step("repeat_A_same_containers", lambda: self.repeat("A"))
        self.step("update_A_to_B", lambda: self.change("B"))
        self.step("repeat_B_same_containers", lambda: self.repeat("B"))
        self.step("manual_same_schema_rollback_B_to_A", lambda: self.change("A"))
        self.step("second_update_A_to_B", lambda: self.change("B"))
        self.step("remove_containers_reinstall_preserved_volumes", self.recreate)
        self.step("bad_manifest_pin", lambda: self.blocked("MANIFEST_PIN_MISMATCH", pin="0" * 64), negative=True)
        self.step("actual_corrupt_archive", self.corrupt_archive, negative=True)
        self.step("copied_state", self.copied_state, negative=True)
        self.step("missing_and_recreated_volume", self.missing_and_drift, negative=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "tooling", "source-b", "transfer", "work", "receipt"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args(argv)
    report = {"status": "FAIL", "contract": CONTRACT, "steps": [],
              "negativeCases": [], "productionAuthorized": False, "realModelExecution": False,
              "startedAt": datetime.now(timezone.utc).isoformat(), "stage": "preflight"}
    receiver = None
    support = None
    try:
        require(not args.work.exists(), "RECEIVER_WORK_MUST_BE_FRESH")
        args.work.mkdir(parents=True)
        report["runner"] = runner_metadata("receiver")
        for path, sha in ((args.candidate, report["runner"]["head"]), (args.tooling, TOOLING), (args.source_b, SOURCES["B"])):
            source_guard(path, sha)
        require(platform.python_version() == (args.candidate / ".python-version").read_text().strip(), "PINNED_PYTHON_REQUIRED")
        report["stage"] = "fresh_engine"
        report["engine"] = engine_metadata(report["runner"]["bootFingerprint"])
        report["before"] = inventory()
        fresh_engine(report["before"], "receiver")
        report["stage"] = "transfer_integrity"
        report["producer"] = validate_transfer(args.transfer, os.environ.get("IZO_PRODUCER_RECEIPT_SHA256", ""), report["runner"], report["engine"])
        require(digest(args.source_b / "tools/docker_shadow_product.py") == report["producer"]["httpClientSha256"], "HTTP_CLIENT_CHANGED")
        report["stage"] = "pinned_support_and_installer_environment"
        support = load_support(args.tooling, args.source_b)
        receiver = Receiver(args, report, support)
        receiver.matrix()
        require(len(report["steps"]) == 11 and all(r["status"] == "PASS" for r in report["steps"]), "POSITIVE_MATRIX_INCOMPLETE")
        report["status"] = "PASS_TEST_LINUX_BUNDLE_ONLY"
    except Exception as error:
        safe_types = (ProofError,) if support is None else (ProofError, support[0].BundleError, support[2].ProductError)
        code = str(error)
        report["reason"] = code if isinstance(error, safe_types) and re.fullmatch(r"[A-Z][A-Z0-9_]{1,100}", code) else "RECEIVER_CONTRACT_FAILED"
    finally:
        if receiver is not None:
            try:
                report["cleanup"] = receiver.cleanup()
            except Exception as error:
                reason = str(error) if isinstance(error, ProofError) else "OWNERSHIP_CHECKED_CLEANUP_BLOCKED"
                report["cleanup"] = {"status": "FAIL", "reason": reason}
                report["status"] = "FAIL"
        report["finishedAt"] = datetime.now(timezone.utc).isoformat()
        write_json(args.receipt, report)
    print(json.dumps({"status": report["status"], "reason": report.get("reason")}))
    return 0 if report["status"] == "PASS_TEST_LINUX_BUNDLE_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
