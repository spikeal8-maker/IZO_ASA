"""Export a synthetic context with real BuildKit and the source's ignore policies.

This checks Dockerfile-specific filtering, not application image/runtime readiness.
Only three policy files are read from source; no application data is copied.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

from tools.docker_test_bundle_runtime import clean_environment

DEV = Path("ops/docker/dev")
POLICIES = {"root": Path(".dockerignore"), **{
    role: DEV / f"Dockerfile.{role}.dockerignore" for role in ("web", "guard")}}
POSITIVE = {
    "frontend/package.json": b'{"name":"synthetic-context-probe"}\n',
    "frontend/package-lock.json": b'{"lockfileVersion":3}\n',
    "frontend/src/keep.txt": b"public frontend source\n",
    "ops/docker/dev/nginx.shadow.conf": b"synthetic nginx input\n",
    "ops/docker/dev/network_guard.py": b"# synthetic guard input\n",
    "ops/docker/dev/comfyui_proxy.py": b"# synthetic Comfy proxy input\n",
    "ops/docker/dev/openrouter_https_proxy.py": b"# synthetic OpenRouter proxy input\n",
}
GUARD_INPUTS = {"ops/docker/dev/network_guard.py", "ops/docker/dev/comfyui_proxy.py",
                "ops/docker/dev/openrouter_https_proxy.py"}
EXCLUDED = (
    "frontend/probe.db", "frontend/probe.sqlite-wal",
    "frontend/probe.db-wal", "frontend/probe.db-shm", "frontend/probe.db-journal",
    "frontend/nested/probe.db-wal", "frontend/nested/probe.db-shm", "frontend/nested/probe.db-journal",
    "frontend/.env", "frontend/.env.local", "frontend/.npmrc", "frontend/secrets/key.txt",
    "frontend/media/private.txt", "frontend/node_modules/cache.txt", "frontend/dist/bundle.js",
    "frontend/screenshots/private.png", "frontend/test-results/private.txt",
    "frontend/playwright-report/private.txt", "frontend/blob-report/private.txt",
    ".env", "backend/private.txt", "unrelated.txt",
    "ops/unrelated/private.txt", "ops/docker/unrelated/private.txt", "ops/docker/dev/unrelated/private.txt",
)


class ProbeFailure(RuntimeError):
    pass


def policies(source):
    result = {}
    for name, relative in POLICIES.items():
        path = source / relative
        if (not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(source)
                or path.stat().st_size > 65536):
            raise ProbeFailure("CONTEXT_POLICY_INPUT_INVALID")
        result[name] = path.read_bytes()
    return result


def fixture(root, policy):
    for name, relative in POLICIES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(policy[name])
    for name, content in {**POSITIVE, **dict.fromkeys(EXCLUDED, b"synthetic excluded marker\n")}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    for role in ("web", "guard"):
        (root / DEV / f"Dockerfile.{role}").write_text("FROM scratch\nCOPY . /context/\n", encoding="ascii")


def inspect_export(output, role):
    expected = {name: content for name, content in POSITIVE.items()
                if (name in GUARD_INPUTS) == (role == "guard")}
    root = output / "context"
    files, unsafe = [], []
    if root.is_dir() and not root.is_symlink():
        for path in root.rglob("*"):
            name = path.relative_to(root).as_posix()
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                unsafe.append(name)
            elif path.is_file():
                files.append(name)
    actual = set(files)
    unexpected, missing = sorted(actual - expected.keys()), sorted(expected.keys() - actual)
    contents = not missing and not unsafe and all(
        (root / name).read_bytes() == content for name, content in expected.items())
    return {"status": "PASS" if not unexpected and not missing and contents else "FAIL",
            "files": sorted(files), "unexpected": unexpected, "missing": missing,
            "unsafe": sorted(unsafe), "contentsVerified": contents}


def probe(source, context):
    source = source.resolve(strict=True)
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", context):
        raise ProbeFailure("EXPLICIT_DOCKER_CONTEXT_REQUIRED")
    policy = policies(source)
    environment = clean_environment()
    def git(*args):
        return subprocess.run(["git", "-C", str(source), *args], env=environment, check=True,
                              capture_output=True, text=True, timeout=30).stdout.strip()
    report = {"contract": "DOCKER-CANONICAL-CANDIDATE-002", "status": "FAIL",
              "sourceSha": git("rev-parse", "HEAD"), "sourceDirty": bool(git("status", "--porcelain")),
              "context": context, "ignoreSha256": {k: hashlib.sha256(v).hexdigest() for k, v in policy.items()},
              "roles": {}, "applicationImageBuild": False}
    with tempfile.TemporaryDirectory(prefix="izo-canonical-context-") as temporary:
        root = Path(temporary); inputs = root / "inputs"
        fixture(inputs, policy)
        for role in ("web", "guard"):
            output = root / ("export-" + role)
            if "," in str(output):
                raise ProbeFailure("BUILD_EXPORT_PATH_UNSUPPORTED")
            command = ["docker", "--context", context, "buildx", "build", "--network=none", "--no-cache",
                       "--progress=plain", "--file", str(inputs / DEV / f"Dockerfile.{role}"),
                       "--output", "type=local,dest=" + str(output), str(inputs)]
            result = subprocess.run(command, env=environment, capture_output=True, timeout=180)
            if result.returncode:
                report["reason"] = "BUILDKIT_CONTEXT_EXPORT_FAILED"
                report["roles"][role] = {"status": "FAIL", "exitCode": result.returncode,
                    "buildLogSha256": hashlib.sha256(result.stdout + result.stderr).hexdigest()}
                return report
            report["roles"][role] = inspect_export(output, role)
    if all(value["status"] == "PASS" for value in report["roles"].values()):
        report["status"] = "PASS_CONTEXT_EXPORT_ONLY"
    else:
        report["reason"] = "CONTEXT_EXCLUSIONS_OR_INPUTS_FAILED"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--context", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.receipt.exists() or args.receipt.is_symlink():
        parser.error("Receipt already exists; preserve the prior evidence.")
    try:
        report = probe(args.source, args.context)
    except (ProbeFailure, OSError, subprocess.SubprocessError) as error:
        report = {"status": "FAIL", "reason": str(error) if isinstance(error, ProbeFailure)
                  else "CONTEXT_COMMAND_UNAVAILABLE_OR_TIMEOUT"}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    with args.receipt.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True); stream.write("\n")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PASS_CONTEXT_EXPORT_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
