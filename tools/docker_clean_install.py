"""Exact-source Docker/browser acceptance on a disposable GitHub-hosted Linux VM."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from tools.docker_shadow import HOST_ENV, OWNER, ROOT, Shadow
from tools.docker_shadow_executor import compare_isolated, guest_identity
from tools.docker_shadow_product import ProductFlow
from tools.docker_shadow_smoke import prove

REPOSITORY = "spikeal8-maker/IZO_ASA"
SHA = re.compile(r"[0-9a-f]{40}")
STORAGE_PROBE = r'''
import hashlib,json,sqlite3
from pathlib import Path
db=sqlite3.connect('file:/home/izo/data/app.sqlite3?mode=ro',uri=True)
integrity=[r[0] for r in db.execute('PRAGMA integrity_check')]
tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
db.close()
root=Path('/home/izo/media')
files={}
for p in sorted(root.rglob('*')):
    if p.is_file():
        if p.is_symlink() or len(files)>=500 or p.stat().st_size>20000000:
            raise RuntimeError('STORAGE_FIXTURE_LIMIT')
        files[p.relative_to(root).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
print(json.dumps({'integrity':integrity,'tables':tables,'media':files}))
'''


class AcceptanceError(RuntimeError):
    """Fixed diagnostic codes; never raw subprocess output or credentials."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise AcceptanceError(code)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def error_code(error: Exception) -> str:
    value = str(error)
    return value if re.fullmatch(r"[A-Z][A-Z0-9_]{2,120}", value) else "ACCEPTANCE_OPERATION_FAILED"


def host_admission(source: str, base: str, evidence: Path) -> dict:
    require(SHA.fullmatch(source) is not None and SHA.fullmatch(base) is not None,
            "ACCEPTANCE_SHA_INVALID")
    require(platform.system() == "Linux" and platform.machine() in {"x86_64", "amd64"},
            "ACCEPTANCE_LINUX_X64_REQUIRED")
    require(os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("GITHUB_REPOSITORY") == REPOSITORY
            and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
            and os.environ.get("GITHUB_SHA") == source, "ACCEPTANCE_DISPOSABLE_RUNNER_REQUIRED")
    temporary = Path(os.environ.get("RUNNER_TEMP", "/nonexistent")).resolve()
    require(temporary.is_dir() and evidence.resolve().is_relative_to(temporary)
            and evidence.resolve() != temporary, "ACCEPTANCE_EVIDENCE_LOCATION_INVALID")
    require(not evidence.exists(), "ACCEPTANCE_PREVIOUS_EVIDENCE_EXISTS")
    require(shutil.disk_usage(ROOT).free >= 8 * 1024**3, "ACCEPTANCE_DISK_RESERVE_REQUIRED")
    memory = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    require(int(memory["MemAvailable"].split()[0]) >= 3 * 1024**2,
            "ACCEPTANCE_MEMORY_RESERVE_REQUIRED")
    return {"os": platform.platform(), "architecture": platform.machine(),
            "python": platform.python_version(), "runnerEnvironment": "github-hosted",
            "runId": os.environ["GITHUB_RUN_ID"], "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
            "workflow": os.environ.get("GITHUB_WORKFLOW"), "machineIdentitySha256": guest_identity(),
            "availableMemoryKiB": int(memory["MemAvailable"].split()[0]),
            "availableDiskBytes": shutil.disk_usage(ROOT).free}


def ports() -> tuple[int, int]:
    sockets = []
    try:
        for _ in range(2):
            connection = socket.socket()
            connection.bind(("127.0.0.1", 0))
            sockets.append(connection)
        chosen = tuple(connection.getsockname()[1] for connection in sockets)
        require(all(20000 <= value <= 65535 for value in chosen), "ACCEPTANCE_PORT_RANGE_INVALID")
        return chosen
    finally:
        for connection in sockets:
            connection.close()


def owned_inventory(shadow: Shadow) -> dict:
    shadow.ownership_guard()
    result = {"containers": [row["Id"] for row in shadow.containers()]}
    for kind in ("volume", "network"):
        result[kind + "s"] = shadow.docker(kind, "ls", "-q", "--filter",
                                            f"label=com.docker.compose.project={shadow.project}").split()
    return result


def require_fresh(shadow: Shadow) -> None:
    require(not any(owned_inventory(shadow).values()), "ACCEPTANCE_PROJECT_NOT_FRESH")


def cleanup_owned(shadow: Shadow, admitted_fresh: bool) -> dict:
    require(admitted_fresh, "ACCEPTANCE_CLEANUP_NOT_ADMITTED")
    shadow.config()
    before = owned_inventory(shadow)
    # Ownership is rechecked immediately before this project's explicit deletion.
    shadow.ownership_guard()
    shadow.compose("down", "--volumes", capture=True, timeout=120)
    after = owned_inventory(shadow)
    require(not any(after.values()), "ACCEPTANCE_OWNED_RESOURCES_REMAIN")
    return {"status": "PASS", "removed": before, "remaining": after,
            "imagesAndBuildCache": "DISPOSABLE_RUNNER_LIFECYCLE", "globalPrune": False}


def backend_id(shadow: Shadow) -> str:
    shadow.ownership_guard()
    rows = [row for row in shadow.containers()
            if row["Config"]["Labels"].get("com.docker.compose.service") == "backend"]
    require(len(rows) == 1 and rows[0]["State"]["Running"], "ACCEPTANCE_BACKEND_NOT_READY")
    return rows[0]["Id"]


def inside_backend(shadow: Shadow, code: str) -> dict:
    raw = shadow.docker("exec", backend_id(shadow), "python", "-c", code, timeout=20)
    require(len(raw) < 200000, "ACCEPTANCE_CONTAINER_REPORT_TOO_LARGE")
    result = json.loads(raw)
    require(isinstance(result, dict), "ACCEPTANCE_CONTAINER_REPORT_INVALID")
    return result


def provider_receipt(shadow: Shadow, minimum: int) -> dict:
    result = inside_backend(shadow, "from pathlib import Path; "
                            "print(Path('/tmp/izo-shadow-provider-receipt.json').read_text())")
    require(result.get("fixture") == "controlled-comfyui-v1", "ACCEPTANCE_PROVIDER_MARKER_MISSING")
    provider = result["provider"]
    require(provider.get("model_execution") is False and provider["counts"].get("accepted", 0) >= minimum
            and len(provider["jobs"]) >= minimum
            and all(job["state"] == "completed" for job in provider["jobs"]),
            "ACCEPTANCE_PROVIDER_WIRE_NOT_PROVEN")
    return result


def storage(shadow: Shadow) -> dict:
    result = inside_backend(shadow, STORAGE_PROBE)
    require(result.get("integrity") == ["ok"] and result.get("media"),
            "ACCEPTANCE_STORAGE_INVALID")
    return result


def telemetry(shadow: Shadow) -> dict:
    rows = shadow.containers()
    images = shadow.image_guard(shadow.config())
    metadata = json.loads(shadow.docker("image", "inspect", *sorted(set(images.values()))))
    stats = shadow.docker("stats", "--no-stream", "--format", "{{json .}}",
                          *[row["Id"] for row in rows])
    return {"images": images, "imageSizes": {row["Id"]: row["Size"] for row in metadata},
            "containers": [{"id": row["Id"], "image": row["Image"],
                "service": row["Config"]["Labels"]["com.docker.compose.service"],
                "user": row["Config"]["User"], "startedAt": row["State"]["StartedAt"],
                "memoryLimitBytes": row["HostConfig"]["Memory"],
                "cpuLimitNano": row["HostConfig"]["NanoCpus"]} for row in rows],
            "sample": [json.loads(line) for line in stats.splitlines() if line]}


def redact_logs(raw: str) -> str:
    text = raw[-60000:]
    sensitive = re.compile(r"(?i)(authorization|cookie|password|secret|api[_-]?key|token)[\"'\s:=]")
    text = "\n".join("[REDACTED_SENSITIVE_LOG_LINE]" if sensitive.search(line) else line
                     for line in text.splitlines())
    text = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [REDACTED]", text)
    text = re.sub(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+", "[FIXTURE_EMAIL]", text)
    text = re.sub(r"[A-Za-z0-9_+/=-]{24,}", "[REDACTED_LONG_VALUE]", text)
    return text


def browser(shadow: Shadow, directory: Path, attestation: dict) -> dict:
    signup = ProductFlow(attestation)
    try:
        signup.register(signup.owner, 3)
        _, email, password = signup.credentials[0]
        signup.owner.request("POST", "/api/auth/session/logout-v2", {})
        payload = json.dumps({"origin": attestation["origin"], "sourceSha": shadow.sha,
                              "email": email, "password": password, "output": str(directory)})
        child_env = {key: os.environ[key] for key in HOST_ENV if key in os.environ}
        finished = subprocess.run(["node", str(ROOT / "tools/docker_clean_browser.mjs")],
                    input=payload, text=True, capture_output=True, timeout=180,
                    cwd=ROOT, env=child_env, check=False)
        payload = password = email = ""
        receipt = directory / "browser.json"
        require(receipt.is_file(), "ACCEPTANCE_BROWSER_REPORT_MISSING")
        result = json.loads(receipt.read_text())
        require(finished.returncode == 0 and result.get("status") == "PASS",
                result.get("errorCode", "ACCEPTANCE_BROWSER_FAILED"))
        return result
    finally:
        cleanup = signup.close()
        save(directory / "signup-cleanup.json", cleanup)
        require(cleanup.get("sessionCleanup") == "PASS", "ACCEPTANCE_BROWSER_SIGNUP_CLEANUP_FAILED")


def execute_run(shadow: Shadow, directory: Path, *, build: bool, base: str, host: dict) -> dict:
    directory.mkdir(parents=True, exist_ok=False)
    report = {"status": "FAIL", "repository": REPOSITORY, "sourceSha": shadow.sha,
              "baseSha": base, "checkoutSha": shadow.sha, "project": shadow.project,
              "startedAt": now(), "host": host, "buildPerformed": build,
              "origin": f"http://127.0.0.1:{shadow.web_port}",
              "apiOrigin": f"http://127.0.0.1:{shadow.api_port}", "checks": {}, "timings": {},
              "limitations": {"modelExecution": False, "production": "NOT_VERIFIED",
                              "D2": "NOT_RUN", "liveIntegrations": "NOT_VERIFIED"}}
    flow, admitted, foreign = None, False, None
    stage = "admission"
    try:
        shadow.source_guard()
        config = shadow.config()
        report["configSha256"] = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        require_fresh(shadow)
        admitted = True
        foreign = shadow.executor.foreign_snapshot(shadow.project)
        save(directory / "foreign-before.json", foreign)
        stage, started = "build-start", time.monotonic()
        shadow.up(build=build)
        report["timings"]["buildAndFirstReadySeconds"] = round(time.monotonic() - started, 3)
        report["checks"]["D1-01"] = {"status": "PASS", "cleanCheckout": True,
                "buildPerformed": build, "imageSource": shadow.sha}
        stage, started = "topology", time.monotonic()
        prove(shadow, directory / "topology.json", build=False)
        topology = json.loads((directory / "topology.json").read_text())
        require(topology.get("status") == "PASS", "ACCEPTANCE_TOPOLOGY_NOT_PROVEN")
        report["timings"]["topologySeconds"] = round(time.monotonic() - started, 3)
        attestation = {"origin": report["origin"], "sourceSha": shadow.sha, "project": shadow.project,
            "isolatedData": True, "fakeProviderOnly": True, "networkEgressDenied": True,
            "externalEffectsDisabled": True, "proof": "topology.json"}
        save(directory / "attestation.json", attestation)
        stage, started = "product-api", time.monotonic()
        flow = ProductFlow(attestation)
        report["product"] = flow.run()
        report["timings"]["apiProductSeconds"] = round(time.monotonic() - started, 3)
        report["checks"]["D1-03"] = {"status": "PASS", "evidence": "product.auth"}
        report["checks"]["D1-05"] = {"status": "PASS", "evidence": "product.ownershipGalleryReuse"}
        stage, started = "browser", time.monotonic()
        report["browser"] = browser(shadow, directory / "browser", attestation)
        report["timings"]["browserSeconds"] = round(time.monotonic() - started, 3)
        report["checks"]["D1-02"] = {"status": "PASS", "evidence": "topology.json; browser/browser.json"}
        report["checks"]["D1-06"] = {"status": "PASS", "evidence": "product.publicationModeration; browser"}
        report["providerBeforeRecreate"] = provider_receipt(shadow, 3)
        report["checks"]["D1-04"] = {"status": "PASS", "evidence": "product.generation; browser; providerBeforeRecreate"}
        stage = "persistence-baseline"
        before = storage(shadow)
        report["resourcesBeforeRecreate"] = telemetry(shadow)
        stage, started = "recreate", time.monotonic()
        shadow.up(build=False, recreate=True)
        report["timings"]["recreateReadySeconds"] = round(time.monotonic() - started, 3)
        report["persistence"] = flow.verify_persistence()
        after = storage(shadow)
        require(before["media"] == after["media"], "ACCEPTANCE_MEDIA_CHANGED_AFTER_RECREATE")
        report["storage"] = {"before": before, "after": after}
        report["providerAfterRecreate"] = provider_receipt(shadow, 0)
        require(report["providerAfterRecreate"]["provider"]["counts"].get("accepted", 0) == 0,
                "ACCEPTANCE_COMPLETED_JOB_REPLAYED")
        report["resourcesAfterRecreate"] = telemetry(shadow)
        report["checks"]["D1-07"] = {"status": "PASS", "evidence": "persistence; storage; providerAfterRecreate",
                "sessionSecret": "DETERMINISTIC_APP_ENV_TEST_ONLY"}
        report["status"] = "PASS"
    except Exception as error:
        report["errorCode"], report["failedStage"] = error_code(error), stage
    finally:
        if flow is not None:
            report["product"] = flow.checks
            report["sessionCleanup"] = flow.close()
            if report["sessionCleanup"]["sessionCleanup"] != "PASS":
                report["status"] = "FAIL"
        if admitted:
            try:
                raw = shadow.compose("logs", "--no-color", "--tail", "150", timeout=20)
                (directory / "containers.redacted.log").write_text(redact_logs(raw), encoding="utf-8")
            except Exception as error:
                report["logCapture"] = error_code(error)
            try:
                report["cleanup"] = cleanup_owned(shadow, admitted)
                after = shadow.executor.foreign_snapshot(shadow.project)
                save(directory / "foreign-after.json", after)
                report["foreignResources"] = compare_isolated(foreign, after)
                require(report["foreignResources"]["status"] == "PASS", "ACCEPTANCE_FOREIGN_RESOURCE_CHANGED")
                require((directory / "containers.redacted.log").is_file(), "ACCEPTANCE_LOGS_MISSING")
                if (directory / "browser/browser.json").is_file() and list(directory.glob("browser/*.png")):
                    report["checks"]["D1-08"] = {"status": "PASS", "evidence": "cleanup; foreignResources; browser; logs"}
            except Exception as error:
                report["cleanupError"], report["status"] = error_code(error), "FAIL"
        for number in range(1, 9):
            report["checks"].setdefault(f"D1-{number:02}", {"status": "NOT_RUN"})
        if any(report["checks"][f"D1-{number:02}"]["status"] != "PASS" for number in range(1, 9)):
            report["status"] = "FAIL"
        if report["status"] != "PASS" and stage not in {"admission", "build-start"}:
            report["checks"].setdefault("failure", {"status": "FAIL", "stage": stage})
        report["finishedAt"] = now()
        save(directory / "receipt.json", report)
        print(json.dumps({"project": shadow.project, "status": report["status"],
                          "failedStage": report.get("failedStage"), "errorCode": report.get("errorCode")}))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--replica", type=int, choices=(1, 2), required=True)
    args = parser.parse_args()
    try:
        host = host_admission(args.source_sha, args.base_sha, args.evidence_dir)
        args.evidence_dir.mkdir(parents=True)
        seed = Shadow("izo-asa-shadow-admission", args.source_sha)
        info = json.loads(seed.run(["docker", "--context", "default", "info", "--format", "{{json .}}"] ))
        host.update(engineId=info["ID"], docker=info["ServerVersion"], cpuCount=info["NCPU"],
                    dockerMemoryBytes=info["MemTotal"])
        host["compose"] = seed.run(["docker", "--context", "default", "compose", "version", "--short"])
        reports = []
        for number in range(1, 4):
            project = f"izo-asa-shadow-ci-{host['runId']}-{host['attempt']}-{args.replica}-{number}"
            web, api = ports()
            shadow = Shadow(project, args.source_sha, web, api, fixture=True,
                executor_context="default", engine_id=host["engineId"],
                machine_sha256=host["machineIdentitySha256"])
            report = execute_run(shadow, args.evidence_dir / f"run-{number}",
                                 build=number == 1, base=args.base_sha, host=host)
            reports.append(report)
            # Never retry a failed fixture behind a later success in the same run.
            if report["status"] != "PASS":
                break
        passed = len(reports) == 3 and all(report["status"] == "PASS" for report in reports)
        save(args.evidence_dir / "summary.json", {"status": "PASS" if passed else "FAIL",
            "repository": REPOSITORY, "sourceSha": args.source_sha, "baseSha": args.base_sha,
            "replica": args.replica, "host": host, "completedFixtureRuns": len(reports),
            "runs": [{"project": report["project"], "status": report["status"],
                      "checks": report["checks"]} for report in reports]})
        return 0 if passed else 1
    except Exception as error:
        print("CLEAN_INSTALL_FAILED " + error_code(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
