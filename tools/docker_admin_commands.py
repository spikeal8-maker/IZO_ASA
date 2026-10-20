"""Bounded, exact-source Docker HTTP proof on an ephemeral GitHub hosted runner.

Every mutation is addressed by an exact, run-specific resource name. Cleanup
requires all ownership labels again and never prunes shared resources. Private
fixture sessions remain inside the two disposable volumes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


OWNER = "ADMIN-COMMAND-IDEMPOTENCY-001"
OWNER_LABEL = "io.izo.admin-proof.owner"
RUN_LABEL = "io.izo.admin-proof.run"
SOURCE_LABEL = "io.izo.admin-proof.source"
PREFIX = "IZO_ADMIN_RECEIPT:"
DOCKER_ENDPOINT = "unix:///var/run/docker.sock"
DOCKER_OVERRIDES = ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH",
                    "DOCKER_CONFIG", "DOCKER_API_VERSION", "BUILDX_BUILDER", "BUILDX_CONFIG", "BUILDKIT_HOST")


class ProofError(RuntimeError):
    pass


def docker_environment(env: dict[str, str]) -> dict[str, str]:
    if any(env.get(key) for key in DOCKER_OVERRIDES):
        raise ProofError("ADMIN_PROOF_DOCKER_OVERRIDE_REJECTED")
    return {key: value for key, value in env.items() if key not in DOCKER_OVERRIDES}


def command(args: list[str], *, stdin: str | None = None, timeout: int = 60,
            allow_missing: bool = False, log_path: Path | None = None, env: dict | None = None) -> str | None:
    if args[0] == "docker":
        env = docker_environment(dict(os.environ) if env is None else env)
        if not Path("/var/run/docker.sock").is_socket():
            raise ProofError("ADMIN_PROOF_LOCAL_DOCKER_SOCKET_MISSING")
        args = ["docker", "--host", DOCKER_ENDPOINT, *args[1:]]
    result = subprocess.run(args, input=stdin, text=True, capture_output=True, timeout=timeout, env=env)
    if log_path is not None:
        log_path.write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        missing = ("No such container:", "No such image:", "No such object:", "no such volume")
        if allow_missing and any(item in result.stderr for item in missing):
            return None
        raise ProofError(f"ADMIN_PROOF_COMMAND_FAILED:{args[0]}:{result.returncode}")
    return result.stdout.strip()


def admission(root: Path, output: Path, sha: str, env: dict[str, str]) -> str:
    docker_environment(env)  # Fail before even read-only Docker calls or cleanup.
    run = f"{env.get('GITHUB_RUN_ID', '')}-{env.get('GITHUB_RUN_ATTEMPT', '')}"
    if (env.get("GITHUB_ACTIONS") != "true" or env.get("RUNNER_ENVIRONMENT") != "github-hosted"
            or env.get("RUNNER_OS") != "Linux" or sys.platform != "linux"
            or not re.fullmatch(r"[0-9]{1,20}-[0-9]{1,4}", run)
            or not re.fullmatch(r"[a-f0-9]{40}", sha)):
        raise ProofError("ADMIN_PROOF_HOSTED_SOURCE_ADMISSION_REJECTED")
    temporary = Path(env.get("RUNNER_TEMP", "/invalid-runner-temporary-root")).resolve()
    if not output.is_relative_to(temporary) or output == temporary or output.is_relative_to(root):
        raise ProofError("ADMIN_PROOF_OUTPUT_SCOPE_REJECTED")
    if command(["git", "-C", str(root), "rev-parse", "HEAD"]) != sha:
        raise ProofError("ADMIN_PROOF_SOURCE_SHA_MISMATCH")
    if command(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"]):
        raise ProofError("ADMIN_PROOF_SOURCE_DIRTY")
    origin = command(["git", "-C", str(root), "config", "--get", "remote.origin.url"])
    if origin not in ("https://github.com/spikeal8-maker/IZO_ASA", "https://github.com/spikeal8-maker/IZO_ASA.git",
                      "git@github.com:spikeal8-maker/IZO_ASA.git"):
        raise ProofError("ADMIN_PROOF_SOURCE_REPOSITORY_MISMATCH")
    return run


def resource_names(sha: str, run: str) -> dict[str, str]:
    stem = f"izo-admin-{sha[:10]}-{run}"
    return {"api": stem + "-api", "seed": stem + "-seed", "data": stem + "-data",
            "media": stem + "-media", "image": stem + ":proof"}


def inspect(kind: str, name: str) -> dict | None:
    value = command(["docker", kind, "inspect", name], allow_missing=True)
    if value is None:
        return None
    values = json.loads(value)
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise ProofError("ADMIN_PROOF_INSPECTION_INVALID")
    return values[0]


def labels(sha: str, run: str) -> dict[str, str]:
    return {OWNER_LABEL: OWNER, RUN_LABEL: run, SOURCE_LABEL: sha}


def require_owned(value: dict, kind: str, sha: str, run: str) -> None:
    if not isinstance(value, dict):
        raise ProofError("ADMIN_PROOF_RESOURCE_OWNER_MISMATCH")
    actual = value.get("Labels") if kind == "volume" else (value.get("Config") or {}).get("Labels")
    if not isinstance(actual, dict) or any(actual.get(key) != expected for key, expected in labels(sha, run).items()):
        raise ProofError("ADMIN_PROOF_RESOURCE_OWNER_MISMATCH")


def label_args(sha: str, run: str) -> list[str]:
    return [part for key, value in labels(sha, run).items() for part in ("--label", f"{key}={value}")]


def inventory() -> dict[str, list[str]]:
    commands = {
        "containers": ["docker", "container", "ls", "--all", "--quiet", "--no-trunc"],
        "volumes": ["docker", "volume", "ls", "--quiet"],
        "networks": ["docker", "network", "ls", "--quiet", "--no-trunc"],
        "images": ["docker", "image", "ls", "--quiet", "--no-trunc"],
    }
    return {kind: sorted(set(command(args).splitlines())) for kind, args in commands.items()}


def assert_foreign_identities(before: dict[str, list[str]], after: dict[str, list[str]]) -> None:
    if any(not set(previous).issubset(after.get(kind, [])) for kind, previous in before.items()):
        raise ProofError("ADMIN_PROOF_FOREIGN_RESOURCE_IDENTITY_CHANGED")


def preflight(names: dict[str, str]) -> dict:
    engine = command(["docker", "info", "--format", "{{.OSType}}|{{.ID}}"])
    if not engine.startswith("linux|") or not re.fullmatch(r"[A-Za-z0-9:-]+", engine.split("|", 1)[1]):
        raise ProofError("ADMIN_PROOF_DOCKER_OS_REJECTED")
    for key, name in names.items():
        kind = "container" if key in ("api", "seed") else "image" if key == "image" else "volume"
        if inspect(kind, name) is not None:
            raise ProofError("ADMIN_PROOF_RESERVED_NAME_ALREADY_EXISTS")
    return {"endpoint": DOCKER_ENDPOINT, "socketVerified": True, "osType": "linux",
            "daemonIdSha256": hashlib.sha256(engine.split("|", 1)[1].encode()).hexdigest()}


def clean(names: dict[str, str], sha: str, run: str) -> list[str]:
    errors = []
    for key in ("api", "seed", "data", "media", "image"):
        kind = "container" if key in ("api", "seed") else "image" if key == "image" else "volume"
        try:
            value = inspect(kind, names[key])
            if value is None:
                continue
            require_owned(value, kind, sha, run)
            options = ["--force"] if kind == "container" else ["--no-prune"] if kind == "image" else []
            command(["docker", kind, "rm", *options, names[key]])
            if inspect(kind, names[key]) is not None:
                raise ProofError("ADMIN_PROOF_RESOURCE_REMAINS")
        except Exception as exc:
            errors.append(f"{key}:{type(exc).__name__}:{exc}")
    return errors


def container_args(name: str, names: dict[str, str], sha: str, run: str) -> list[str]:
    environment = {
        "APP_ENV": "test", "ENV": "test", "MODE": "test",
        "DATABASE_URL": "/home/izo/data/app.sqlite3", "MEDIA_DIR": "/home/izo/media",
        "IZO_SECRET_DIR": "/home/izo/data/secrets", "IZO_ADMIN_COMMAND_PROOF_RUN": run,
        "BOT_MODE": "disabled", "BOT_UPDATES_MODE": "disabled", "MAX_UPDATES_MODE": "disabled",
        "TELEGRAM_POLLING_ENABLED": "false", "MAX_POLLING_ENABLED": "false", "LOCAL_LTX_ENABLED": "false",
        "IZO_PHONE_TTS_PROVIDER": "fake", "EMAIL_OTP_DEBUG_RETURN_CODE": "false", "NO_PROXY": "localhost,127.0.0.1",
    }
    for key in ("COMFYUI_BASE_URL", "OLLAMA_BASE_URL", "QWEN_ASR_BASE_URL", "LOCAL_LTX_COMFYUI_BASE_URL",
                "OPENROUTER_BASE_URL", "MAX_API_BASE_URL", "CBR_DAILY_XML_URL", "USD_RUB_FALLBACK_URL"):
        environment[key] = "http://127.0.0.1:1"
    for key in ("TELEGRAM_BOT_TOKEN", "BOT_TOKEN", "MAX_BOT_TOKEN", "OPENROUTER_API_KEY", "OPENAI_API_KEY",
                "FAL_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "REPLICATE_API_TOKEN", "SESSION_TOKEN_HMAC_KEY",
                "MAX_WEBHOOK_URL", "BACKEND_PUBLIC_URL", "RUNTIME_ALERT_WEBHOOK_URL", "ADMIN_ONE_TIME_CODE",
                "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        environment[key] = ""
    return ["docker", "run", "--name", name, *label_args(sha, run), "--network", "none", "--user", "10001:10001",
            "--cpus", "2", "--memory", "2g", "--pids-limit", "128", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true", "--restart", "no",
            "--mount", f"type=volume,source={names['data']},target=/home/izo/data",
            "--mount", f"type=volume,source={names['media']},target=/home/izo/media",
            *[part for key, value in environment.items() for part in ("--env", f"{key}={value}")]]


def receipt(raw: str, phase: str) -> dict:
    candidates = [line[len(PREFIX):] for line in raw.splitlines() if line.startswith(PREFIX)]
    if len(candidates) != 1:
        raise ProofError("ADMIN_PROOF_RUNTIME_RECEIPT_MISSING_OR_DUPLICATE")
    value = json.loads(candidates[0])
    if not isinstance(value, dict) or value.get("status") != "PASS" or value.get("phase") != phase:
        raise ProofError("ADMIN_PROOF_RUNTIME_PHASE_FAILED")
    return value


def validate_proof(phases: dict[str, dict]) -> None:
    seed, exercise, replay = (phases.get(name, {}) for name in ("seed", "exercise", "replay"))
    if (any(value.get("phase") != name or value.get("status") != "PASS" for name, value in phases.items())
            or seed.get("targets") != 10 or seed.get("browserTargets") != 4
            or exercise.get("races") != 10 or exercise.get("negativeCases") != 12
            or exercise.get("realHttp") is not True or replay.get("realHttp") is not True
            or replay.get("replayedCommands") != 10 or replay.get("sameSession") is not True
            or replay.get("sameLedgerAuditPlanDates") is not True
            or replay.get("browserReplays") != 4 or replay.get("sqliteIntegrity") != "ok"
            or not re.fullmatch(r"[a-f0-9]{64}", replay.get("mediaSha256", ""))):
        raise ProofError("ADMIN_PROOF_REQUIRED_EVIDENCE_INCOMPLETE")


def validate_browser(value: dict, sha: str) -> None:
    cases = value.get("cases", [])
    if (value.get("status") != "PASS" or value.get("sourceSha") != sha
            or value.get("realCrm") is not True or value.get("realHttp") is not True
            or value.get("blockedRequests") != [] or len(cases) != 4
            or {(item.get("viewport"), item.get("kind")) for item in cases}
            != {(viewport, kind) for viewport in ("desktop", "mobile") for kind in ("tokens", "plan")}):
        raise ProofError("ADMIN_PROOF_BROWSER_EVIDENCE_INCOMPLETE")
    for item in cases:
        expected = {"ledger": 1, "grants": int(item["kind"] == "plan"), "audit": 1, "commands": 1}
        if (item.get("status") != "PASS" or item.get("httpRequests") != 3
                or item.get("closedDialogLateAck") is not True
                or item.get("lostResponseInjected") is not True or item.get("reloadedInput") is not True
                or item.get("sameKeyResponseAndState") is not True or item.get("effects") != expected):
            raise ProofError("ADMIN_PROOF_BROWSER_RETRY_OR_EFFECT_FAILED")


def health(name: str, sha: str, run: str) -> None:
    script = ("import json,urllib.request; "
              "v=json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)); "
              "assert v.get('ok') is True and v.get('ready') is True")
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        value = inspect("container", name)
        if value is None:
            raise ProofError("ADMIN_PROOF_API_MISSING")
        require_owned(value, "container", sha, run)
        if value.get("HostConfig", {}).get("NetworkMode") != "none" or value.get("HostConfig", {}).get("PortBindings"):
            raise ProofError("ADMIN_PROOF_API_ISOLATION_MISMATCH")
        if not value.get("State", {}).get("Running"):
            raise ProofError("ADMIN_PROOF_API_EXITED")
        try:
            command(["docker", "exec", name, "python", "-c", script], timeout=5)
            return
        except ProofError:
            time.sleep(1)
    raise ProofError("ADMIN_PROOF_API_NOT_READY")


def save(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def execute(root: Path, output: Path, sha: str, run: str) -> dict:
    names = resource_names(sha, run)
    engine = preflight(names)
    before = inventory()
    output.mkdir(parents=True, exist_ok=True)
    save(output / "resources.json", {"sha": sha, "run": run, "names": names, "before": before})
    result = {"status": "FAIL", "owner": OWNER, "sourceSha": sha, "run": run, "phases": {}, "dockerEngine": engine,
              "scope": "AM-001/AM-002 concurrent HTTP and recreated-container replay; full D3 remains open"}
    runtime = (root / "tools/docker_admin_commands_runtime.py").read_text(encoding="utf-8")
    try:
        command(["docker", "build", "--builder", "default", "--progress", "plain", "--file", str(root / "ops/docker/dev/Dockerfile.backend"),
                 "--build-arg", f"IZO_SOURCE_SHA={sha}", *label_args(sha, run), "--tag", names["image"], str(root)],
                timeout=1200, log_path=output / "build.log")
        built = inspect("image", names["image"])
        require_owned(built, "image", sha, run)
        if built["Config"]["Labels"].get("org.opencontainers.image.revision") != sha:
            raise ProofError("ADMIN_PROOF_IMAGE_REVISION_MISMATCH")
        image_id = result["imageId"] = built["Id"]
        for key in ("data", "media"):
            command(["docker", "volume", "create", *label_args(sha, run), names[key]])
        raw = command([*container_args(names["seed"], names, sha, run), "--rm", "--interactive", image_id, "python", "-", "seed"],
                      stdin=runtime, timeout=180, log_path=output / "runtime-seed.log")
        result["phases"]["seed"] = receipt(raw, "seed")
        container_ids = []
        for phase in ("exercise", "replay"):
            container_ids.append(command([*container_args(names["api"], names, sha, run), "--detach", image_id]))
            health(names["api"], sha, run)
            raw = command(["docker", "exec", "--interactive", names["api"], "python", "-", phase],
                          stdin=runtime, timeout=180, log_path=output / f"runtime-{phase}.log")
            result["phases"][phase] = receipt(raw, phase)
            if phase == "exercise":
                command(["node", str(root / "frontend/e2e-admin-command-retry.mjs")], timeout=300,
                        env={**os.environ, "PROOF_SOURCE_SHA": sha, "PROOF_OUTPUT": str(output), "PROOF_IMAGE_ID": image_id},
                        log_path=output / "browser.log")
                result["browser"] = json.loads((output / "browser-receipt.json").read_text(encoding="utf-8"))
                validate_browser(result["browser"], sha)
            require_owned(inspect("container", names["api"]), "container", sha, run)
            command(["docker", "container", "stop", "--time", "20", names["api"]], timeout=40)
            command(["docker", "container", "rm", names["api"]])
        if len(set(container_ids)) != 2:
            raise ProofError("ADMIN_PROOF_CONTAINER_NOT_RECREATED")
        result["containerIds"] = container_ids
        validate_proof(result["phases"])
        result["status"] = "PASS"
    except Exception as exc:
        result["failure"] = f"{type(exc).__name__}:{exc}"
        try:
            current = inspect("container", names["api"])
            if current is not None:
                require_owned(current, "container", sha, run)
                command(["docker", "logs", "--tail", "200", names["api"]], log_path=output / "api.log")
        except Exception:
            result["diagnostics"] = "owned-container-log-unavailable"
    finally:
        errors = clean(names, sha, run)
        result["cleanup"] = {"status": "FAIL" if errors else "PASS", "errors": errors}
        try:
            assert_foreign_identities(before, inventory())
            result["foreignResourceIdentities"] = "PRESERVED"
            result["foreignInventorySha256"] = hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest()
        except Exception as exc:
            result["foreignResourceIdentities"] = "FAIL"
            errors.append(f"{type(exc).__name__}:{exc}")
        if errors:
            result["status"] = "FAIL"
            result["cleanup"]["status"] = "FAIL"
        save(output / "receipt.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cleanup-only", action="store_true")
    args = parser.parse_args()
    root, output = Path(__file__).resolve().parents[1], args.output.resolve()
    run = admission(root, output, args.sha, dict(os.environ))
    if args.cleanup_only:
        plan = output / "resources.json"
        if not plan.is_file():
            return 0  # The run never passed preflight and created its ownership plan.
        saved = json.loads(plan.read_text(encoding="utf-8"))
        expected = resource_names(args.sha, run)
        if saved.get("sha") != args.sha or saved.get("run") != run or saved.get("names") != expected:
            raise ProofError("ADMIN_PROOF_CLEANUP_PLAN_MISMATCH")
        errors = clean(expected, args.sha, run)
        assert_foreign_identities(saved["before"], inventory())
        if errors:
            raise ProofError("ADMIN_PROOF_FINAL_CLEANUP_FAILED")
        return 0
    try:
        result = execute(root, output, args.sha, run)
    except Exception as exc:
        output.mkdir(parents=True, exist_ok=True)
        result = {"status": "FAIL", "sourceSha": args.sha, "failure": f"{type(exc).__name__}:{exc}"}
        save(output / "receipt.json", result)
    print(json.dumps({key: result.get(key) for key in ("status", "sourceSha", "imageId", "failure", "cleanup")}, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
