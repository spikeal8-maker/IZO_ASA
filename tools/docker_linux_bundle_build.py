"""Bounded GitHub Linux producer for the existing, immutable TEST ZIP builder."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
REPOSITORY = "spikeal8-maker/IZO_ASA"
CONTRACT = "DOCKER-LINUX-BUNDLE-ACCEPTANCE-002"
TOOLING = "2fc621342721b1716e2ed898e24502115b71cb53"
SOURCES = {"A": "1030abdafc32a0f11fbc4a6593acd435eb1bbdfd",
           "B": "f51c316176bf2609ccb9271c00a358a7b1f02768"}
PROJECT = "izo-asa-bundle-linux-proof"
PORTS = {"web": 48734, "api": 48735}
COMPOSE = ("compose.yml", "compose.shadow.yml", "compose.acceptance.yml")
HOST_KEYS = {"PATH", "HOME", "LANG", "LC_ALL", "TMP", "TEMP", "TMPDIR", "XDG_RUNTIME_DIR"}


class ProofError(RuntimeError):
    """A fixed diagnostic, safe to publish without subprocess output."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ProofError(code)


def environment() -> dict:
    return {**{k: v for k, v in os.environ.items() if k in HOST_KEYS},
            "PYTHONDONTWRITEBYTECODE": "1"}


def run(args: list[str], *, cwd: Path | None = None, env: dict | None = None,
        timeout: int = 60) -> str:
    try:
        value = subprocess.run(args, cwd=cwd, env=environment() if env is None else env,
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ProofError("COMMAND_UNAVAILABLE_OR_TIMEOUT") from None
    require(value.returncode == 0, "COMMAND_FAILED")
    require(len(value.stdout) <= 8 * 1024**2, "COMMAND_OUTPUT_TOO_LARGE")
    return value.stdout.strip()


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def source_guard(root: Path, sha: str) -> None:
    require(re.fullmatch(r"[0-9a-f]{40}", sha or "") is not None, "HEAD_INVALID")
    origin = run(["git", "-C", str(root), "remote", "get-url", "origin"])
    origins = {"https://github.com/" + REPOSITORY, "git@github.com:" + REPOSITORY,
               "ssh://git@github.com/" + REPOSITORY}
    require(run(["git", "-C", str(root), "rev-parse", "HEAD"]) == sha
            and origin.removesuffix(".git") in origins
            and not run(["git", "-C", str(root), "status", "--porcelain"]),
            "CLEAN_EXACT_REPOSITORY_REQUIRED")


def boot_fingerprint() -> str:
    value = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    require(re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value) is not None,
            "LINUX_BOOT_ID_UNAVAILABLE")
    return hashlib.sha256(value.encode()).hexdigest()


def runner_metadata(expected_job: str) -> dict:
    require(os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("IZO_RUNNER_ENVIRONMENT") == "github-hosted"
            and os.environ.get("IZO_RUNNER_OS") == "Linux"
            and os.environ.get("IZO_RUNNER_ARCH") == "X64"
            and platform.system() == "Linux" and platform.machine() in {"x86_64", "AMD64"},
            "GITHUB_HOSTED_LINUX_X64_REQUIRED")
    release = platform.freedesktop_os_release()
    require(release.get("ID") == "ubuntu" and release.get("VERSION_ID") == "22.04",
            "UBUNTU_2204_REQUIRED")
    require(os.environ.get("GITHUB_REPOSITORY") == REPOSITORY
            and os.environ.get("GITHUB_JOB") == expected_job, "WORKFLOW_IDENTITY_INVALID")
    result = {key: os.environ.get(env, "") for key, env in {
        "runId": "GITHUB_RUN_ID", "attempt": "GITHUB_RUN_ATTEMPT", "job": "GITHUB_JOB",
        "runner": "IZO_RUNNER_NAME", "head": "IZO_EXPECTED_HEAD"}.items()}
    require(all(result.values()) and re.fullmatch(r"[0-9a-f]{40}", result["head"]) is not None,
            "WORKFLOW_METADATA_MISSING")
    return {**result, "environment": "github-hosted", "os": "ubuntu-22.04", "arch": "X64",
            "python": platform.python_version(), "bootFingerprint": boot_fingerprint()}


def engine_metadata() -> dict:
    info = json.loads(run(["docker", "--context", "default", "info", "--format", "{{json .}}"] ))
    require(info.get("OSType") == "linux" and info.get("Architecture") in {"x86_64", "amd64"}
            and isinstance(info.get("ID"), str) and info["ID"], "LINUX_AMD64_ENGINE_REQUIRED")
    compose = run(["docker", "--context", "default", "compose", "version", "--short"])
    return {"fingerprint": hashlib.sha256(info["ID"].encode()).hexdigest(),
            "engine": info["ServerVersion"], "compose": compose, "context": "default"}


def inventory() -> dict:
    commands = {"images": ["image", "ls", "-aq", "--no-trunc"],
                "containers": ["ps", "-aq", "--no-trunc"], "volumes": ["volume", "ls", "-q"]}
    return {key: sorted(set(run(["docker", "--context", "default", *args]).split()))
            for key, args in commands.items()}


def fresh_engine(value: dict, role: str) -> None:
    """Validate the inventory already captured by the caller's failure receipt."""
    require(role in {"producer", "receiver"}, "ENGINE_ROLE_INVALID")
    require(not any(value.values()), role.upper() + "_ENGINE_NOT_EMPTY_NO_PRUNE")


def pinned_dockerfiles(source: Path) -> dict:
    result = {}
    for role in ("guard", "backend", "web"):
        path = source / "ops/docker/dev" / ("Dockerfile." + role)
        bases = re.findall(r"^FROM\s+(\S+)", path.read_text(encoding="utf-8"), re.MULTILINE)
        require(bases and all(re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", base) for base in bases),
                "DOCKER_BASE_NOT_DIGEST_PINNED")
        result[role] = {"sha256": digest(path), "bases": bases}
    return result


def build_release(tooling: Path, source: Path, label: str, output: Path, report: dict) -> dict:
    sha = SOURCES[label]
    report["stage"] = "build_" + label + "_source_validation"
    source_guard(source, sha)
    pins = pinned_dockerfiles(source)
    env = {**environment(), "IZO_SOURCE_SHA": sha, "IZO_COMPOSE_PROJECT": PROJECT,
           "IZO_SHADOW_WEB_PORT": str(PORTS["web"]), "IZO_SHADOW_API_PORT": str(PORTS["api"])}
    command = ["docker", "--context", "default", "compose", "--env-file", os.devnull,
               "--project-name", PROJECT]
    for filename in COMPOSE:
        command += ["-f", str(source / "ops/docker/dev" / filename)]
    report["stage"] = "build_" + label + "_images"
    run(command + ["build", "--no-cache", "guard", "backend", "web"], env=env, timeout=1800)
    archive = output / ("release-" + label + ".zip")
    report["stage"] = "build_" + label + "_bundle"
    run([sys.executable, "-B", "-m", "tools.docker_test_bundle", "build", "--source", str(source),
         "--sha", sha, "--project", PROJECT, "--web-port", str(PORTS["web"]),
         "--api-port", str(PORTS["api"]), "--context", "default", "--output", str(archive)],
        cwd=tooling, timeout=600)
    report["stage"] = "build_" + label + "_receipt_validation"
    receipt_path = archive.with_suffix(".receipt.json")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    require(receipt.get("status") == "TEST_BUNDLE_BUILT" and receipt.get("source_sha") == sha
            and receipt.get("tooling_sha") == TOOLING and receipt.get("project") == PROJECT
            and receipt.get("images_embedded") is True and receipt.get("production_authorized") is False
            and receipt.get("archive_sha256") == digest(archive), "BUILD_RECEIPT_INVALID")
    source_guard(source, sha)
    return {"receipt": receipt, "receiptSha256": digest(receipt_path), "dockerfiles": pins}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--tooling", required=True, type=Path)
    parser.add_argument("--source-a", required=True, type=Path)
    parser.add_argument("--source-b", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    report = {"status": "FAIL", "contract": CONTRACT,
              "startedAt": datetime.now(timezone.utc).isoformat(), "productionAuthorized": False, "stage": "preflight"}
    created = False
    try:
        require(not args.output.exists(), "OUTPUT_MUST_BE_FRESH")
        args.output.mkdir(parents=True)
        created = True
        report["runner"] = runner_metadata("producer")
        source_guard(args.candidate, report["runner"]["head"])
        require(platform.python_version() == (args.candidate / ".python-version").read_text().strip(),
                "PINNED_PYTHON_REQUIRED")
        source_guard(args.tooling, TOOLING)
        require(all(not path.resolve().is_relative_to(args.tooling.resolve())
                    for path in (args.source_a, args.source_b, args.output)), "SOURCE_OR_OUTPUT_INSIDE_TOOLING")
        report["stage"] = "fresh_engine"
        report["engine"] = engine_metadata()
        report["before"] = inventory()
        fresh_engine(report["before"], "producer")
        report["toolingSha"] = TOOLING
        report["httpClientSha256"] = digest(args.source_b / "tools/docker_shadow_product.py")
        report["releases"] = {}
        for label, source in (("A", args.source_a), ("B", args.source_b)):
            print("BUILDING_TEST_RELEASE_" + label, flush=True)
            report["releases"][label] = build_release(args.tooling, source, label, args.output, report)
        report["stage"] = "producer_postcheck"
        source_guard(args.tooling, TOOLING)
        source_guard(args.candidate, report["runner"]["head"])
        require(not inventory()["containers"] and not inventory()["volumes"], "PRODUCER_LEFT_RUNTIME_RESOURCES")
        report["status"] = "PASS_TEST_PRODUCER_ONLY"
    except Exception as error:
        report["reason"] = str(error) if isinstance(error, ProofError) else "PRODUCER_CONTRACT_FAILED"
    finally:
        report["finishedAt"] = datetime.now(timezone.utc).isoformat()
        if created:
            write_json(args.output / "producer.json", report)
    print(json.dumps({"status": report["status"], "reason": report.get("reason")}))
    return 0 if report["status"] == "PASS_TEST_PRODUCER_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
