from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .package import AgentPackageError, _assert_owner
from .registry import load_registry, resolve_repo_root

DEFAULT_IMAGE = "izo-asa-agent-sandbox:v1"
PLATFORM = "linux/amd64"
CONTEXT_REL = Path("ops/docker/agent-sandbox")
DEFAULT_KEY_REL = Path(".ssh/izo_asa_coding_readonly")
DEFAULT_KNOWN_HOSTS_REL = Path(".ssh/known_hosts")
SOURCE_FINGERPRINT_LABEL = "io.izo.agent-sandbox.source-fingerprint"


class SandboxError(RuntimeError):
    pass


@dataclass(frozen=True)
class SandboxContext:
    repo: Path
    package_id: str
    base_sha: str
    key_path: Path
    known_hosts_path: Path
    image: str = DEFAULT_IMAGE


def _docker_executable() -> str:
    command = shutil.which("docker")
    if not command:
        raise SandboxError("DOCKER_NOT_FOUND")
    return command


def _required_file(raw: str, default: Path, label: str) -> Path:
    candidate = Path(raw).expanduser() if raw.strip() else Path.home() / default
    candidate = candidate.resolve()
    if not candidate.is_file():
        raise SandboxError(f"{label}_MISSING path={candidate}")
    return candidate


def resolve_context(repo_root: Path | str, image: str = DEFAULT_IMAGE) -> SandboxContext:
    repo = resolve_repo_root(repo_root)
    payload = load_registry(repo)
    _ownership, _entry, manifest, _manifest_path = _assert_owner(repo, payload)
    key = _required_file(
        os.getenv("IZO_AGENT_READONLY_KEY", ""),
        DEFAULT_KEY_REL,
        "READONLY_DEPLOY_KEY",
    )
    known_hosts = _required_file(
        os.getenv("IZO_AGENT_KNOWN_HOSTS", ""),
        DEFAULT_KNOWN_HOSTS_REL,
        "KNOWN_HOSTS",
    )
    return SandboxContext(
        repo=repo,
        package_id=manifest.id,
        base_sha=manifest.base_sha,
        key_path=key,
        known_hosts_path=known_hosts,
        image=image,
    )


def source_fingerprint(ctx: SandboxContext) -> str:
    context = ctx.repo / CONTEXT_REL
    if not context.is_dir():
        raise SandboxError(f"SANDBOX_CONTEXT_MISSING path={context}")
    files = sorted(path for path in context.rglob("*") if path.is_file())
    if not files:
        raise SandboxError("SANDBOX_CONTEXT_EMPTY")
    digest = hashlib.sha256()
    for path in files:
        if path.is_symlink():
            raise SandboxError(
                f"SANDBOX_CONTEXT_SYMLINK_FORBIDDEN path={path.relative_to(context)}"
            )
        relative = path.relative_to(context).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return "sha256:" + digest.hexdigest()


def build_args(ctx: SandboxContext) -> list[str]:
    context = ctx.repo / CONTEXT_REL
    dockerfile = context / "Dockerfile"
    if not dockerfile.is_file():
        raise SandboxError(f"SANDBOX_DOCKERFILE_MISSING path={dockerfile}")
    fingerprint = source_fingerprint(ctx)
    return [
        _docker_executable(),
        "build",
        "--pull",
        "--platform",
        PLATFORM,
        "--label",
        f"{SOURCE_FINGERPRINT_LABEL}={fingerprint}",
        "--tag",
        ctx.image,
        str(context),
    ]


def _mount(source: Path, target: str, *, readonly: bool) -> str:
    mode = "ro" if readonly else "rw"
    return f"{source}:{target}:{mode}"


def run_args(
    ctx: SandboxContext,
    command: list[str],
    *,
    image_ref: str,
    interactive: bool = False,
) -> list[str]:
    if not command:
        raise SandboxError("SANDBOX_COMMAND_REQUIRED")
    if not image_ref.startswith("sha256:"):
        raise SandboxError("SANDBOX_EXACT_IMAGE_ID_REQUIRED")
    args = [
        _docker_executable(),
        "run",
        "--rm",
        "--platform",
        PLATFORM,
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "256",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=256m",
        "--tmpfs",
        "/home/agent:rw,nosuid,nodev,uid=10001,gid=10001,mode=0700,size=64m",
        "--tmpfs",
        "/workspace/.runtime/agent:rw,nosuid,nodev,noexec,uid=10001,gid=10001,mode=0700,size=1m",
        "--env",
        "HOME=/home/agent",
        "--env",
        "GH_CONFIG_DIR=/home/agent/.config/gh",
        "--env",
        "GIT_TERMINAL_PROMPT=0",
        "--env",
        "IZO_REPOSITORY=spikeal8-maker/IZO_ASA",
        "--env",
        f"IZO_PACKAGE_ID={ctx.package_id}",
        "--env",
        f"IZO_PACKAGE_BASE_SHA={ctx.base_sha}",
        "--volume",
        _mount(ctx.repo, "/workspace", readonly=False),
        "--volume",
        _mount(ctx.repo / ".git", "/workspace/.git", readonly=True),
        "--volume",
        _mount(ctx.key_path, "/run/izo-ssh/id", readonly=True),
        "--volume",
        _mount(ctx.known_hosts_path, "/run/izo-ssh/known_hosts", readonly=True),
    ]
    if interactive:
        args.append("-i")
        if sys.stdin.isatty() and sys.stdout.isatty():
            args.append("-t")
    args.extend([image_ref, *command])
    return args


def _run(args: list[str], *, cwd: Path) -> int:
    completed = subprocess.run(args, cwd=cwd, check=False)
    return completed.returncode


def _validated_image_id(ctx: SandboxContext) -> tuple[str, str]:
    expected_fingerprint = source_fingerprint(ctx)
    completed = subprocess.run(
        [_docker_executable(), "image", "inspect", ctx.image],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise SandboxError(f"SANDBOX_IMAGE_MISSING image={ctx.image}")
    try:
        payload = json.loads(completed.stdout)
        image = payload[0]
        image_id = str(image["Id"])
        labels = image.get("Config", {}).get("Labels") or {}
        actual_fingerprint = str(labels.get(SOURCE_FINGERPRINT_LABEL, ""))
    except (json.JSONDecodeError, IndexError, KeyError, TypeError) as exc:
        raise SandboxError("SANDBOX_IMAGE_INSPECT_INVALID") from exc
    if not image_id.startswith("sha256:"):
        raise SandboxError("SANDBOX_IMAGE_ID_INVALID")
    if actual_fingerprint != expected_fingerprint:
        raise SandboxError(
            "SANDBOX_IMAGE_SOURCE_MISMATCH "
            f"expected={expected_fingerprint} actual={actual_fingerprint or '<missing>'} "
            f"image={ctx.image}"
        )
    return image_id, expected_fingerprint


def build(ctx: SandboxContext) -> int:
    rc = _run(build_args(ctx), cwd=ctx.repo)
    if rc:
        return rc
    image_id, fingerprint = _validated_image_id(ctx)
    print(
        "AGENT_SANDBOX_BUILT "
        + json.dumps(
            {
                "image": ctx.image,
                "imageId": image_id,
                "platform": PLATFORM,
                "sourceFingerprint": fingerprint,
            },
            sort_keys=True,
        )
    )
    return 0


def probe(ctx: SandboxContext) -> int:
    image_id, fingerprint = _validated_image_id(ctx)
    print(
        "AGENT_SANDBOX_PROBE_START "
        + json.dumps(
            {
                "packageId": ctx.package_id,
                "image": ctx.image,
                "imageId": image_id,
                "sourceFingerprint": fingerprint,
            },
            sort_keys=True,
        )
    )
    return _run(
        run_args(ctx, ["boundary-probe"], image_ref=image_id),
        cwd=ctx.repo,
    )


def run(ctx: SandboxContext, command: str, *, interactive: bool) -> int:
    image_id, fingerprint = _validated_image_id(ctx)
    print(
        "AGENT_SANDBOX_RUN "
        + json.dumps(
            {
                "packageId": ctx.package_id,
                "image": ctx.image,
                "imageId": image_id,
                "sourceFingerprint": fingerprint,
            },
            sort_keys=True,
        )
    )
    return _run(
        run_args(
            ctx,
            ["sh", "-lc", command],
            image_ref=image_id,
            interactive=interactive,
        ),
        cwd=ctx.repo,
    )


def resolve_run_command(command: str, command_base64: str) -> str:
    if command and command_base64:
        raise SandboxError("SANDBOX_COMMAND_CONFLICT")
    if command_base64:
        try:
            raw = base64.b64decode(command_base64, validate=True)
            decoded = raw.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
            raise SandboxError("SANDBOX_COMMAND_ENCODING_INVALID") from exc
        if not decoded:
            raise SandboxError("SANDBOX_COMMAND_REQUIRED")
        return decoded
    return command or "sh"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent sandbox")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("build")
    sub.add_parser("probe")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--command", default="")
    run_parser.add_argument("--command-base64", default="")
    run_parser.add_argument("--interactive", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        ctx = resolve_context(Path(args.repo_root), args.image)
        if args.action == "build":
            return build(ctx)
        if args.action == "probe":
            return probe(ctx)
        command = resolve_run_command(args.command, args.command_base64)
        return run(ctx, command, interactive=args.interactive)
    except (SandboxError, AgentPackageError) as exc:
        print(f"AGENT_SANDBOX_ERROR {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
