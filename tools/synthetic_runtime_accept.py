"""Plan-pinned synthetic runtime lifecycle. Only an explicit cleanup removes TEST data."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
import synthetic_runtime_checks as checks

SOURCES = {"A": "1030abdafc32a0f11fbc4a6593acd435eb1bbdfd", "B": "f51c316176bf2609ccb9271c00a358a7b1f02768"}
STATUS = "PASS_SYNTHETIC_RUNTIME_LIFECYCLE_ONLY"
require = checks.require


def sha(value, length=64):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{" + str(length) + "}", value) is not None


def safe_reason(error):
    code = str(error)
    return code if re.fullmatch(r"[A-Z][A-Z0-9_]{1,100}", code) else type(error).__name__


def load_plan(path, pin):
    require(sha(pin) and checks.digest(checks.plain(path)) == pin, "PLAN_PIN_MISMATCH")
    plan = checks.read_json(path)
    require(set(plan) == {"version", "scope", "toolingSha", "bundles", "support", "controllerHashes",
                          "observationSeconds", "retainSyntheticCredentials"}
            and type(plan["version"]) is int and plan["version"] == 1, "PLAN_SHAPE_INVALID")
    scope = plan["scope"]
    require(scope["os"] == platform.system().lower() and scope["host"].casefold() == platform.node().casefold()
            and sha(scope["engineFingerprint"]), "HOST_SCOPE_MISMATCH")
    require(re.fullmatch(r"izo-asa-bundle-runtime[a-z0-9-]{3,20}", scope["project"]) is not None, "PROJECT_SCOPE_INVALID")
    root = checks.plain(scope["root"])
    require(root.is_dir() and set(scope["ports"]) == {"web", "api"}
            and all(type(p) is int and 1024 <= p <= 65535 for p in scope["ports"].values())
            and len(set(scope["ports"].values())) == 2, "ROOT_OR_PORTS_INVALID")
    require(sha(plan["toolingSha"], 40) and set(plan["bundles"]) == {"A", "B"}, "BUNDLE_PINS_REQUIRED")
    require(type(plan["observationSeconds"]) is int and 360 <= plan["observationSeconds"] <= 900
            and type(plan["retainSyntheticCredentials"]) is bool, "OBSERVATION_OR_PRIVATE_INTENT_INVALID")
    expected_scripts = {"synthetic_runtime_accept.py", "synthetic_runtime_checks.py"}
    require(set(plan["controllerHashes"]) == expected_scripts, "CONTROLLER_PINS_REQUIRED")
    for name, expected in plan["controllerHashes"].items():
        require(sha(expected) and checks.digest(Path(__file__).parent / name, canonical=True) == expected, "CONTROLLER_HASH_MISMATCH")
    modules = plan["support"]["moduleHashes"]
    require(set(modules) == {"docker_test_bundle_format", "docker_test_bundle_runtime"}
            and all(sha(pin) for pin in modules.values()) and sha(plan["support"]["httpClientSha256"]), "SUPPORT_PINS_REQUIRED")
    for label, item in plan["bundles"].items():
        require(set(item) == {"archiveSha256", "manifestSha256", "receiptSha256"}
                and all(sha(pin) for pin in item.values()), "ARCHIVE_PINS_REQUIRED")
        archive = root / ("release-" + label + ".zip")
        receipt = archive.with_suffix(".receipt.json")
        require(checks.digest(checks.plain(receipt)) == item["receiptSha256"], "BUILD_RECEIPT_PIN_MISMATCH")
        value = checks.read_json(receipt)
        require(value.get("status") == "TEST_BUNDLE_BUILT" and value.get("source_sha") == SOURCES[label]
                and value.get("tooling_sha") == plan["toolingSha"] and value.get("project") == scope["project"]
                and value.get("images_embedded") is True and value.get("production_authorized") is False
                and value.get("manifest_sha256") == item["manifestSha256"]
                and value.get("archive_sha256") == item["archiveSha256"]
                and archive.stat().st_size == value.get("archive_bytes")
                and checks.digest(checks.plain(archive)) == item["archiveSha256"], "ARCHIVE_IDENTITY_MISMATCH")
    return plan


def installer_environment(runtime, root):
    environment = runtime.clean_environment()
    executable = shutil.which("docker", path=environment.get("PATH"))
    require(executable is not None, "DOCKER_CLI_UNAVAILABLE")
    if os.name == "nt":
        system = Path(os.environ["SystemRoot"])
        paths = [Path(sys.executable).parent, Path(executable).parent, system / "System32", system]
    else:
        folder = root / "installer-bin"; folder.mkdir()
        for name, target in (("python", sys.executable), ("python3", sys.executable), ("docker", executable)):
            (folder / name).symlink_to(Path(target).resolve())
        paths = [folder]
    environment["PATH"] = os.pathsep.join(map(str, paths))
    require(shutil.which("docker", path=environment["PATH"]) is not None
            and shutil.which("python", path=environment["PATH"]) is not None
            and all(shutil.which(name, path=environment["PATH"]) is None for name in ("git", "node", "npm")),
            "INSTALLER_PATH_NOT_ISOLATED")
    return environment


class Controller:
    def __init__(self, plan, plan_pin, support):
        self.plan, self.pin = plan, plan_pin
        self.fmt, self.runtime, self.http = support
        self.scope = plan["scope"]; self.root = checks.plain(self.scope["root"])
        self.state = self.root / "installed"; self.project = self.scope["project"]
        self.docker = self.runtime.Docker(self.scope["context"])
        self.active, self.manifests, self.owner, self.accepted = "B", {}, None, None
        self.claim = None
        self.product = None; self.before = None
        self.receipt = self.root / "runtime-acceptance.json"
        self.report = {"status": "RUNNING", "planSha256": plan_pin, "project": self.project,
                       "startedAt": datetime.now(timezone.utc).isoformat(), "steps": [],
                       "productionAuthorized": False, "realModelExecution": False, "automaticCleanup": False}

    def release(self, label=None):
        return self.state / "releases" / self.plan["bundles"][label or self.active]["manifestSha256"]

    def save(self):
        self.runtime.atomic_json(self.receipt, self.report)

    def stage(self, name, operation):
        row = {"name": name, "status": "RUNNING"}; self.report["steps"].append(row); self.save()
        started = time.monotonic(); print("START " + name, flush=True)
        row["evidence"] = operation()
        row.update(status="PASS", seconds=round(time.monotonic() - started, 3)); self.save()
        print("PASS " + name, flush=True)

    def namespace_names(self, *, installed, lease=False):
        volumes = {self.project + "_sqlite-data", self.project + "_media-data", self.project + "-installation"} if installed else set()
        if lease: volumes.add(self.project + "-operation-lock")
        for kind, expected in (("volume", volumes), ("network", {self.project + "_shadow"} if installed else set())):
            names = set(self.docker.run(kind, "ls", "--format", "{{.Name}}").splitlines())
            relevant = {n for n in names if n == self.project or n.startswith((self.project + "_", self.project + "-"))}
            require(relevant == expected, "UNEXPECTED_NAMESPACE_RESOURCE")
            marked = set(self.docker.run(kind, "ls", "--filter", "label=com.docker.compose.project=" + self.project,
                                         "--format", "{{.Name}}").splitlines())
            require(marked <= expected, "UNEXPECTED_MARKED_RESOURCE")

    def preflight(self):
        require(self.docker.engine() == self.scope["engineFingerprint"], "ENGINE_SCOPE_CHANGED")
        require(not any((self.root / name).exists() for name in
            ("installed", "incoming-A", "incoming-B", "runtime-acceptance.json", "controller.lock", "private", "installer-bin")), "QA_ROOT_NOT_FRESH")
        self.namespace_names(installed=False)
        marked = self.docker.run("ps", "-aq", "--filter", "label=com.docker.compose.project=" + self.project).split()
        self.before = checks.inventory(self.docker)
        require(not marked and not any(c["Name"].lstrip("/") == self.project
            or c["Name"].lstrip("/").startswith((self.project + "-", self.project + "_"))
            for c in self.before["containers"].values()), "QA_CONTAINER_ALREADY_EXISTS")
        sockets = []
        try:
            for port in self.scope["ports"].values():
                item = socket.socket(socket.AF_INET, socket.SOCK_STREAM); sockets.append(item)
                if os.name == "nt": item.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                item.bind(("127.0.0.1", port)); item.listen(1)
        finally:
            for item in sockets: item.close()
        return {"status": "READ_ONLY_PREFLIGHT_VERIFIED", "project": self.project, "ports": self.scope["ports"],
                "foreignCounts": {key: len(value) for key, value in self.before.items()}, "expectedStages": 11, "expectedJobs": 9}

    def unpack(self):
        for label, record in self.plan["bundles"].items():
            path = self.root / ("incoming-" + label)
            self.fmt.extract(self.root / ("release-" + label + ".zip"), record["archiveSha256"], path)
            manifest = self.fmt.verify(path, record["manifestSha256"])
            require(manifest["format"] == 2 and self.fmt.bundle_profile(manifest) == self.fmt.RUNTIME
                    and manifest["project"] == self.project and manifest["ports"] == self.scope["ports"]
                    and manifest["source_sha"] == SOURCES[label] and manifest["tooling_sha"] == self.plan["toolingSha"]
                    and not (path / ".git").exists(), "RUNTIME_BUNDLE_IDENTITY_MISMATCH")
            self.manifests[label] = manifest
        return {"profiles": ["synthetic-runtime", "synthetic-runtime"], "sources": SOURCES, "gitDirectory": False}

    def install(self, label, *, update=False, persistent=False):
        root = self.release(label) if persistent else self.root / ("incoming-" + label)
        args = [sys.executable, "-B", str(root / "docker_test_bundle_runtime.py"), "install", "--test-only",
                "--context", self.scope["context"], "--state-dir", str(self.state),
                "--manifest-sha256", self.plan["bundles"][label]["manifestSha256"]]
        if update: args.append("--allow-code-update")
        result = subprocess.run(args, cwd=root, env=self.environment, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=300, check=False)
        value = json.loads(result.stdout)
        require(result.returncode == 0 and value.get("status") == "TEST_RUNTIME_VERIFIED"
                and value.get("profile") == "synthetic-runtime" and value.get("source_sha") == SOURCES[label], "INSTALLER_DID_NOT_VERIFY")
        self.active = label
        owner = checks.read_json(self.state / "owner.json")
        require(self.owner is None or self.owner == owner, "OWNER_RECEIPT_CHANGED")
        self.owner = owner
        self.capture()  # Verify actual ordinary process, locality and idle DB before any new HTTP mutation.
        return {"releaseId": value["release_id"], "sourceSha": SOURCES[label], "profile": value["profile"]}

    def scope_check(self, *, lease=False):
        manifest = self.manifests[self.active]
        require(self.docker.engine() == self.scope["engineFingerprint"], "ENGINE_SCOPE_CHANGED")
        expected = {"engine": self.scope["engineFingerprint"], "id": self.owner["id"], "project": self.project,
                    "profile": "synthetic-runtime", "test_only": True,
                    "state": checks.hashlib.sha256(os.path.normcase(str(self.state.absolute())).encode()).hexdigest()}
        require(self.owner == expected and checks.read_json(self.state / "owner.json") == expected
                and re.fullmatch(r"[0-9a-f]{32}", self.owner["id"]) is not None, "OWNER_BINDING_CHANGED")
        active = checks.read_json(self.state / "active.json")
        require(active.get("manifest_sha256") == self.plan["bundles"][self.active]["manifestSha256"]
                and active.get("profile") == "synthetic-runtime" and active.get("engine") == self.owner["engine"]
                and active.get("source_sha") == SOURCES[self.active] and active.get("project") == self.project
                and active.get("status") == "TEST_RUNTIME_VERIFIED" and active.get("production_authorized") is False,
                "ACTIVE_RECEIPT_CHANGED")
        self.namespace_names(installed=True, lease=lease)
        resources = self.runtime.owned_resources(self.docker, manifest)
        require(self.runtime.volume_identity(resources, manifest, self.owner) == active["volumes"], "VOLUME_RECEIPT_DRIFT")
        claim = json.loads(self.docker.run("volume", "inspect", self.project + "-installation"))[0]
        require(claim["Name"] == self.project + "-installation" and isinstance(claim.get("CreatedAt"), str)
            and claim["CreatedAt"] and claim["Labels"] == {"io.izo.bundle": self.fmt.OWNER, "io.izo.bundle.installation": self.owner["id"],
            "io.izo.bundle.state": self.owner["state"], "io.izo.bundle.engine": self.owner["engine"],
            "io.izo.bundle.profile": "synthetic-runtime"} and claim["Driver"] == claim["Scope"] == "local"
            and not claim.get("Options"), "INSTALLATION_CLAIM_CHANGED")
        claim_identity = checks.volume_metadata({"volumes": [claim]})[claim["Name"]]
        require(self.claim is None or self.claim == claim_identity, "INSTALLATION_CLAIM_DRIFT")
        self.claim = claim_identity
        own = {"containers": {c["Id"] for c in resources["containers"]},
               "volumes": {v["Name"] for v in resources["volumes"]} | {claim["Name"]},
               "networks": {n["Name"] for n in resources["networks"]}}
        if lease: own["volumes"].add(self.project + "-operation-lock")
        checks.foreign_unchanged(checks.inventory(self.docker), self.before, own)
        return resources

    def capture(self, *, lease=False):
        self.scope_check(lease=lease)
        topology = checks.topology(self.runtime, self.docker, self.release(), self.manifests[self.active])
        data = checks.database(self.docker, topology["containers"]["backend"]["id"], self.product.jobs if self.product else [])
        return {"topology": topology, "database": data, "product": self.product.snapshot() if self.product else None}

    def persist(self, *, lease=False):
        current = self.capture(lease=lease)
        require(current["database"] == self.accepted["database"] and current["product"] == self.accepted["product"]
                and current["topology"]["volumes"] == self.accepted["topology"]["volumes"], "LIFECYCLE_DATA_CHANGED")
        self.product.replay_and_compare()
        return current

    def next_generation(self):
        result = self.product.generate()
        self.accepted = self.capture(); self.product.saved = self.accepted["product"]
        return result

    def seed(self):
        self.product = checks.Product(self.http, "http://127.0.0.1:" + str(self.scope["ports"]["web"]))
        result = self.product.register_and_login()
        if self.plan["retainSyntheticCredentials"]:
            self.report["privateCredentials"] = checks.private_credentials(self.root, self.project, self.product.credentials,
                                                                           self.runtime.clean_environment())
        self.product.generate(); self.product.generate(mode="image_to_image")
        self.product.owner.request("POST", "/api/gallery/" + self.product.jobs[0]["image"] + "/favorite", {"isFavorite": True})
        self.accepted = self.capture(); self.product.saved = self.accepted["product"]
        require(self.accepted["product"]["images"][0]["favorite"] is True, "FAVORITE_NOT_PRESERVED")
        return {**result, "completedJobs": 2, "fullJobLinkedCharges": len(self.accepted["database"]["charges"])}

    def repeat(self, *, remove_incoming=False):
        before = self.capture()
        if remove_incoming:
            incoming = checks.plain(self.root / "incoming-B")
            self.fmt.verify(incoming, self.plan["bundles"]["B"]["manifestSha256"]); shutil.rmtree(incoming)
        self.install(self.active, persistent=True)
        after = self.persist()
        require(after["topology"]["containers"] == before["topology"]["containers"], "REPEAT_RECREATED_CONTAINERS")
        return {"persistentCompose": True, "sameContainers": True, "dataUnchanged": True}

    def observe(self):
        initial = self.capture(); start = time.monotonic(); samples = 0
        while time.monotonic() - start < self.plan["observationSeconds"]:
            current = self.capture(); samples += 1
            require(current["topology"]["containers"] == initial["topology"]["containers"], "UPTIME_INTERRUPTED")
            require(current["database"] == self.accepted["database"] and current["product"] == self.accepted["product"], "OBSERVATION_DATA_CHANGED")
            time.sleep(min(5, max(0, self.plan["observationSeconds"] - (time.monotonic() - start))))
        elapsed = time.monotonic() - start
        final = self.persist()
        require(final["topology"]["containers"] == initial["topology"]["containers"], "UPTIME_INTERRUPTED")
        return {"observedSeconds": round(elapsed, 3), "samples": samples, "sameStartedAt": True,
                "postDeadlineGeneration": self.next_generation()}

    def lifecycle(self, kind):
        before = self.persist()
        with self.runtime.engine_lock(self.docker, self.owner):
            self.persist(lease=True)
            root, manifest = self.release(), self.manifests[self.active]
            if kind == "backend-restart": self.docker.compose(root, manifest, "restart", "backend")
            else:
                self.docker.compose(root, manifest, "stop", "web", "backend", "guard")
                self.docker.compose(root, manifest, "up", "-d", "--wait", "--wait-timeout", "120",
                                    "--no-build", "--pull", "never",
                                    "--force-recreate" if kind == "group-recreate" else "--no-recreate")
            self.runtime.wait_health(self.docker, root, manifest, timeout=60)
            after = self.persist(lease=True)
        old, new = before["topology"]["containers"], after["topology"]["containers"]
        for role in old:
            require((old[role]["id"] != new[role]["id"]) == (kind == "group-recreate"), "LIFECYCLE_CONTAINER_TRANSITION_INVALID")
            changed_start = kind != "backend-restart" or role == "backend"
            require((old[role]["startedAt"] != new[role]["startedAt"]) == changed_start, "LIFECYCLE_START_TRANSITION_INVALID")
        return {"operation": kind, "netns": after["topology"]["netns"], "generation": self.next_generation()}

    def reinstall(self):
        before = self.persist()
        with self.runtime.engine_lock(self.docker, self.owner):
            self.persist(lease=True); self.docker.compose(self.release(), self.manifests[self.active], "down")
            resources = self.runtime.owned_resources(self.docker, self.manifests[self.active])
            require(not resources["containers"] and not resources["networks"]
                    and checks.volume_metadata(resources) == before["topology"]["volumes"], "DOWN_INCOMPLETE_OR_VOLUME_DRIFT")
            checks.foreign_unchanged(checks.inventory(self.docker), self.before, {"containers": set(), "networks": set(),
                "volumes": set(before["topology"]["volumes"]) | {self.project + "-installation", self.project + "-operation-lock"}})
        self.install("B", persistent=True)
        after = self.persist()
        require(all(before["topology"]["containers"][role]["id"] != after["topology"]["containers"][role]["id"]
                    for role in ("backend", "web", "guard")), "REINSTALL_DID_NOT_RECREATE")
        return {"volumesPreserved": True, "generation": self.next_generation()}

    def change(self, label):
        self.persist(); self.install(label, update=True, persistent=self.release(label).exists())
        self.persist(); generated = self.next_generation(); self.repeat()
        return {"sourceSha": SOURCES[label], "generation": generated, "exactPinRepeat": "PASS"}

    def run(self):
        self.preflight()
        nonce = uuid.uuid4().hex; lock = self.root / "controller.lock"
        with lock.open("x", encoding="ascii") as stream: stream.write(nonce)
        try:
            self.report["foreignBefore"] = self.before
            self.environment = installer_environment(self.runtime, self.root)
            self.stage("verify_and_extract_A_B", self.unpack)
            self.stage("install_ordinary_B", lambda: self.install("B"))
            self.stage("password_login_two_users_and_two_jobs", self.seed)
            self.stage("remove_incoming_and_repeat_B", lambda: self.repeat(remove_incoming=True))
            self.stage("continuous_uptime_and_live_generation", self.observe)
            for name in ("backend-restart", "group-stop-start", "group-recreate"):
                self.stage(name, lambda value=name: self.lifecycle(value))
            self.stage("down_and_reinstall_preserved_volumes", self.reinstall)
            self.stage("ordinary_B_to_A", lambda: self.change("A"))
            self.stage("ordinary_A_to_B", lambda: self.change("B"))
            require(len(self.report["steps"]) == 11 and len(self.product.jobs) == 9, "MATRIX_INCOMPLETE")
            self.accepted = self.persist()
            tables, accounts = self.accepted["database"]["protectedTables"], self.accepted["product"]["accounts"]
            counts = {role: account["account"]["gallery_used"] for role, account in zip(("owner", "other"), accounts)}
            require(counts == {"owner": 9, "other": 0} and tables["images"]["count"] == tables["jobs"]["count"] == 9
                    and len(self.accepted["database"]["charges"]) == 9, "MATRIX_DOMAIN_COUNTS_CHANGED")
            self.report.update(status=STATUS, activeLabel="B", accepted=self.accepted, owner=self.owner, claim=self.claim,
                               activeReceiptSha256=checks.digest(self.state / "active.json"),
                               ownerReceiptSha256=checks.digest(self.state / "owner.json"), foreignResourcesChanged=0,
                               perUserImages=counts, laterCanariesUse="other", fullQualityWindow=10)
        except Exception as error:
            self.report.update(status="FAILED_RESOURCES_RETAINED", reason=safe_reason(error), automaticRetry=False)
            if self.report["steps"] and self.report["steps"][-1]["status"] == "RUNNING":
                self.report["steps"][-1]["status"] = "FAIL"
        finally:
            self.report["finishedAt"] = datetime.now(timezone.utc).isoformat(); self.save()
            if self.product: self.product.close()
            if lock.is_file() and lock.read_text(encoding="ascii") == nonce: lock.unlink()
        return {"status": self.report["status"], "receipt": str(self.receipt), "receiptSha256": checks.digest(self.receipt)}

    def cleanup(self, receipt_pin):
        require(sha(receipt_pin) and checks.digest(self.receipt) == receipt_pin, "ACCEPTANCE_RECEIPT_PIN_MISMATCH")
        accepted = checks.read_json(self.receipt)
        require(accepted.get("status") == STATUS and accepted.get("planSha256") == self.pin
                and accepted.get("project") == self.project and accepted.get("foreignResourcesChanged") == 0
                and len(accepted.get("steps", [])) == 11 and all(x["status"] == "PASS" for x in accepted["steps"]), "CLEANUP_ACCEPTANCE_REQUIRED")
        require(not (self.root / "controller.lock").exists() and not (self.root / "cleanup.json").exists(), "CLEANUP_ALREADY_ACTIVE_OR_DONE")
        self.owner, self.before = accepted["owner"], accepted["foreignBefore"]
        self.claim = accepted["claim"]
        self.manifests = {"B": self.fmt.verify(self.release(), self.plan["bundles"]["B"]["manifestSha256"])}
        require(checks.digest(self.state / "owner.json") == accepted["ownerReceiptSha256"]
                and checks.digest(self.state / "active.json") == accepted["activeReceiptSha256"], "CLEANUP_RECEIPT_DRIFT")
        if "privateCredentials" in accepted:
            require(checks.digest(self.root / "private/credentials.json") == accepted["privateCredentials"]["sha256"], "PRIVATE_ARTIFACT_CHANGED")
        self.scope_check()
        current = checks.topology(self.runtime, self.docker, self.release(), self.manifests["B"])
        require(current == accepted["accepted"]["topology"], "CLEANUP_RESOURCE_IDENTITY_CHANGED")
        require(checks.database(self.docker, current["containers"]["backend"]["id"], accepted["accepted"]["product"]["jobs"])
                == accepted["accepted"]["database"], "CLEANUP_PROTECTED_DATA_CHANGED")
        result = {"status": "RUNNING", "acceptanceReceiptSha256": receipt_pin, "stage": "acquire-lock",
                  "removedVolumes": [], "archivesAndReceiptsRetained": True, "automaticCleanup": False}
        path = self.root / "cleanup.json"
        self.runtime.atomic_json(path, result)
        try:
            with self.runtime.engine_lock(self.docker, self.owner):
                self.scope_check(lease=True)
                require(checks.topology(self.runtime, self.docker, self.release(), self.manifests["B"]) == current, "CLEANUP_PRESTOP_DRIFT")
                require(checks.database(self.docker, current["containers"]["backend"]["id"], accepted["accepted"]["product"]["jobs"])
                        == accepted["accepted"]["database"], "CLEANUP_PROTECTED_DATA_CHANGED")
                result["stage"] = "compose-down"; self.runtime.atomic_json(path, result)
                self.docker.compose(self.release(), self.manifests["B"], "down")
                resources = self.runtime.owned_resources(self.docker, self.manifests["B"])
                require(not resources["containers"] and not resources["networks"]
                        and checks.volume_metadata(resources) == current["volumes"], "CLEANUP_DOWN_OR_VOLUME_DRIFT")
                checks.foreign_unchanged(checks.inventory(self.docker), self.before, {"containers": set(), "networks": set(),
                    "volumes": set(current["volumes"]) | {self.claim["Name"], self.project + "-operation-lock"}})
                result["containersRemoved"] = 3
                for name, expected in current["volumes"].items():
                    result["stage"] = "remove-owned-data-volume"; self.runtime.atomic_json(path, result)
                    row = json.loads(self.docker.run("volume", "inspect", name))[0]
                    require(checks.volume_metadata({"volumes": [row]})[name] == expected, "CLEANUP_VOLUME_DRIFT")
                    self.docker.run("volume", "rm", name)
                    result["removedVolumes"].append(name); self.runtime.atomic_json(path, result)
                result["stage"] = "remove-owned-claim"; self.runtime.atomic_json(path, result)
                row = json.loads(self.docker.run("volume", "inspect", self.claim["Name"]))[0]
                require(checks.volume_metadata({"volumes": [row]})[row["Name"]] == self.claim, "CLEANUP_CLAIM_DRIFT")
                self.docker.run("volume", "rm", self.claim["Name"])
                result["claimsRemoved"] = 1
            self.namespace_names(installed=False)
            checks.foreign_unchanged(checks.inventory(self.docker), self.before, {"containers": set(), "volumes": set(), "networks": set()})
            result.update(status="PASS_OWNED_SYNTHETIC_CLEANUP", stage="complete", foreignResourcesChanged=0)
        except Exception as error:
            result.update(status="FAILED_RESOURCES_RETAINED", reason=safe_reason(error), automaticRetry=False)
        finally:
            self.runtime.atomic_json(path, result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "run", "cleanup"))
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--acceptance-receipt-sha256")
    args = parser.parse_args()
    try:
        plan = load_plan(args.plan, args.plan_sha256)
        controller = Controller(plan, args.plan_sha256, checks.support(plan))
        result = controller.preflight() if args.action == "preflight" else controller.run() if args.action == "run" else controller.cleanup(args.acceptance_receipt_sha256)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 0 if result["status"].startswith(("PASS_", "READ_ONLY_")) else 1
    except Exception as error:
        print(json.dumps({"status": "BLOCKED_OR_STOPPED", "reason": safe_reason(error), "automaticCleanup": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
