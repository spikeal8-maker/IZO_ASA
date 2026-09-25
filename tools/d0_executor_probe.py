from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PRODUCTION_CREDENTIAL_ENV = (
    "DATABASE_URL",
    "IZO_DATABASE_URL",
    "PRODUCTION_DATABASE_URL",
    "MEDIA_DIR",
    "MEDIA_ROOT",
    "IZO_MEDIA_DIR",
    "PRODUCTION_MEDIA_DIR",
    "TELEGRAM_BOT_TOKEN",
    "MAX_BOT_TOKEN",
    "OPENROUTER_API_KEY",
    "COMFYUI_API_KEY",
    "SMTP_PASSWORD",
    "SMTP_TOKEN",
    "STRIPE_SECRET_KEY",
    "YOOKASSA_SECRET_KEY",
    "PAYMENT_PROVIDER_TOKEN",
    "SESSION_HMAC_SECRET",
    "GH_TOKEN",
    "GITHUB_PAT",
    "GITHUB_OWNER_TOKEN",
    "IZO_GITHUB_TOKEN",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(command: Sequence[str], *, timeout: int = 90, cwd: Path = ROOT) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return {
            "exitCode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
            "timedOut": False,
        }
    except FileNotFoundError:
        return {"exitCode": 127, "stdout": "", "stderr": "COMMAND_NOT_FOUND", "timedOut": False}
    except subprocess.TimeoutExpired:
        return {"exitCode": 124, "stdout": "", "stderr": "COMMAND_TIMEOUT", "timedOut": True}


def _version_text(command: Sequence[str]) -> tuple[str | None, int]:
    result = _run(command, timeout=30)
    text = result["stdout"] or result["stderr"]
    return (text.splitlines()[0].strip() if text else None, int(result["exitCode"]))


def _network_status(result: dict[str, Any], *, extra_ok: bool = True) -> str:
    if result["exitCode"] == 0 and extra_ok:
        return "PASS"
    if result["timedOut"] or result["exitCode"] != 0:
        return "EXTERNAL_VERIFICATION_UNAVAILABLE"
    return "FAIL"


def _probe_record(target_class: str, target: str, result: dict[str, Any], *, extra_ok: bool = True) -> dict[str, Any]:
    return {
        "targetClass": target_class,
        "target": target,
        "status": _network_status(result, extra_ok=extra_ok),
        "exitCode": int(result["exitCode"]),
        "timestamp": utc_now(),
    }


def _read_project_versions() -> tuple[str, str]:
    python_expected = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    node_expected = (ROOT / ".node-version").read_text(encoding="utf-8").strip()
    return python_expected, node_expected


def _normalize_python_version(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(\d+\.\d+\.\d+)", value)
    return match.group(1) if match else None


def _normalize_node_version(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"v?(\d+\.\d+\.\d+)", value)
    return match.group(1) if match else None


def evaluate_receipt(receipt: dict[str, Any]) -> tuple[str, list[str]]:
    violations: list[str] = []
    expected_head = str(receipt.get("expectedHead") or "").lower()
    exact_head = str(receipt.get("exactHead") or "").lower()

    if not SHA_RE.fullmatch(expected_head) or exact_head != expected_head:
        violations.append("EXACT_HEAD_MISMATCH")
    if receipt.get("runnerEnvironment") != "github-hosted":
        violations.append("RUNNER_NOT_GITHUB_HOSTED")
    if receipt.get("usedSelfHostedRunner") is not False:
        violations.append("SELF_HOSTED_RUNNER_USED")
    if receipt.get("runnerOS") != "Linux":
        violations.append("RUNNER_OS_NOT_LINUX")

    expected_python = receipt.get("expectedPythonVersion")
    expected_node = receipt.get("expectedNodeVersion")
    if not receipt.get("pythonVersion") or receipt.get("pythonVersion") != expected_python:
        violations.append("PYTHON_VERSION_MISMATCH")
    if not receipt.get("nodeVersion") or receipt.get("nodeVersion") != expected_node:
        violations.append("NODE_VERSION_MISMATCH")
    if not receipt.get("npmVersion"):
        violations.append("NPM_UNAVAILABLE")
    if not receipt.get("dockerClientVersion"):
        violations.append("DOCKER_CLIENT_UNAVAILABLE")
    if not receipt.get("dockerServerVersion"):
        violations.append("DOCKER_SERVER_UNAVAILABLE")
    if not receipt.get("dockerBuildxVersion"):
        violations.append("DOCKER_BUILDX_UNAVAILABLE")

    probes = receipt.get("networkProbes") or []
    by_class = {str(item.get("targetClass")): item for item in probes}
    for required in ("npm_registry", "pypi", "docker_registry"):
        if required not in by_class or by_class[required].get("status") != "PASS":
            violations.append(f"NETWORK_{required.upper()}_NOT_PASS")

    if receipt.get("productionCredentialPresence") is not False:
        violations.append("PRODUCTION_CREDENTIAL_PRESENT")
    if receipt.get("startedApplication") is not False:
        violations.append("APPLICATION_STARTED")
    if receipt.get("usedD2") is not False:
        violations.append("D2_USED")

    return ("PASS" if not violations else "FAIL"), violations


def collect_live_receipt(output_path: Path) -> dict[str, Any]:
    expected_python, expected_node = _read_project_versions()

    event_name = os.environ.get("D0_EVENT_NAME", "")
    expected_head = os.environ.get("D0_EXPECTED_HEAD", "").lower()
    repository = os.environ.get("D0_REPOSITORY", "")
    runner_environment = os.environ.get("D0_RUNNER_ENVIRONMENT", "")
    runner_os = os.environ.get("D0_RUNNER_OS", "")
    runner_arch = os.environ.get("D0_RUNNER_ARCH", "")
    runner_name = os.environ.get("D0_RUNNER_NAME", "")

    git_result = _run(["git", "rev-parse", "HEAD"], timeout=30)
    exact_head = git_result["stdout"].lower() if git_result["exitCode"] == 0 else ""

    python_raw, python_exit = _version_text(["python", "--version"])
    node_raw, node_exit = _version_text(["node", "--version"])
    npm_raw, npm_exit = _version_text(["npm", "--version"])
    docker_raw, docker_exit = _version_text(["docker", "--version"])
    buildx_raw, buildx_exit = _version_text(["docker", "buildx", "version"])
    docker_pair = _run(
        ["docker", "version", "--format", "{{.Client.Version}}|{{.Server.Version}}"],
        timeout=30,
    )
    docker_client: str | None = None
    docker_server: str | None = None
    if docker_pair["exitCode"] == 0 and "|" in docker_pair["stdout"]:
        docker_client, docker_server = docker_pair["stdout"].split("|", 1)
        docker_client = docker_client.strip() or None
        docker_server = docker_server.strip() or None

    npm_probe_result = _run(
        [
            "npm",
            "view",
            "react@19.2.7",
            "version",
            "--registry=https://registry.npmjs.org/",
            "--json",
        ],
        timeout=90,
    )
    npm_probe = _probe_record(
        "npm_registry",
        "registry.npmjs.org/react@19.2.7",
        npm_probe_result,
        extra_ok="19.2.7" in npm_probe_result["stdout"],
    )

    with tempfile.TemporaryDirectory(prefix="d0-pypi-") as tmp:
        tmp_path = Path(tmp)
        pypi_result = _run(
            [
                "python",
                "-m",
                "pip",
                "download",
                "--no-deps",
                "--disable-pip-version-check",
                "--dest",
                str(tmp_path),
                "--index-url",
                "https://pypi.org/simple",
                "fastapi==0.136.3",
            ],
            timeout=120,
        )
        pypi_probe = _probe_record(
            "pypi",
            "pypi.org/fastapi==0.136.3",
            pypi_result,
            extra_ok=any(tmp_path.iterdir()),
        )

    docker_targets = [
        "docker.io/library/node:24-bookworm-slim",
        "docker.io/library/python:3.11-slim-bookworm",
    ]
    docker_probe_exit = 0
    docker_probe_ok = True
    for target in docker_targets:
        result = _run(["docker", "manifest", "inspect", target], timeout=120)
        if result["exitCode"] != 0:
            docker_probe_exit = int(result["exitCode"])
            docker_probe_ok = False
            break
    docker_probe = {
        "targetClass": "docker_registry",
        "target": " + ".join(docker_targets),
        "status": "PASS" if docker_probe_ok else "EXTERNAL_VERIFICATION_UNAVAILABLE",
        "exitCode": docker_probe_exit,
        "timestamp": utc_now(),
    }

    credential_checks = [
        {"name": name, "present": bool(os.environ.get(name))}
        for name in PRODUCTION_CREDENTIAL_ENV
    ]
    credentials_present = any(item["present"] for item in credential_checks)

    python_version = _normalize_python_version(python_raw) if python_exit == 0 else None
    node_version = _normalize_node_version(node_raw) if node_exit == 0 else None
    npm_version = npm_raw if npm_exit == 0 else None
    docker_version = docker_raw if docker_exit == 0 else None
    buildx_version = buildx_raw if buildx_exit == 0 else None

    receipt: dict[str, Any] = {
        "repository": repository,
        "eventName": event_name,
        "runId": os.environ.get("D0_RUN_ID", ""),
        "runAttempt": int(os.environ.get("D0_RUN_ATTEMPT", "0") or "0"),
        "expectedHead": expected_head,
        "exactHead": exact_head,
        "runnerEnvironment": runner_environment,
        "runnerOS": runner_os,
        "runnerArch": runner_arch,
        "runnerName": runner_name,
        "runnerImage": {
            "imageOS": os.environ.get("ImageOS") or None,
            "imageVersion": os.environ.get("ImageVersion") or None,
        },
        "kernel": platform.release(),
        "machineArch": platform.machine(),
        "expectedPythonVersion": expected_python,
        "expectedNodeVersion": expected_node,
        "pythonVersion": python_version,
        "nodeVersion": node_version,
        "npmVersion": npm_version,
        "dockerVersion": docker_version,
        "dockerClientVersion": docker_client,
        "dockerServerVersion": docker_server,
        "dockerBuildxVersion": buildx_version,
        "networkProbes": [npm_probe, pypi_probe, docker_probe],
        "credentialPresenceChecks": credential_checks,
        "productionCredentialPresence": credentials_present,
        "startedApplication": False,
        "usedSelfHostedRunner": runner_environment != "github-hosted",
        "usedD2": False,
        "timestamp": utc_now(),
    }
    status, violations = evaluate_receipt(receipt)
    receipt["D0_01"] = status
    receipt["violations"] = violations

    output_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="D0-01 GitHub-hosted executor proof")
    parser.add_argument("--output", type=Path, default=Path("d0-executor-receipt.json"))
    args = parser.parse_args()

    receipt = collect_live_receipt(args.output)
    print(f"D0_01={receipt['D0_01']}")
    print(f"EXACT_HEAD={receipt['exactHead']}")
    print(f"RUNNER_ENVIRONMENT={receipt['runnerEnvironment']}")
    if receipt["violations"]:
        print("VIOLATIONS=" + ",".join(receipt["violations"]))
    return 0 if receipt["D0_01"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
