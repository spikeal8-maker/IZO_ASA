from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.agent_system import sandbox
from tools.agent_system.sandbox import (
    DEFAULT_IMAGE,
    PLATFORM,
    SOURCE_FINGERPRINT_LABEL,
    SandboxContext,
    SandboxError,
    _validated_image_id,
    build_args,
    resolve_context,
    resolve_run_command,
    run_args,
    source_fingerprint,
)

ROOT = Path(__file__).resolve().parents[1]
DOCKER_CONTEXT = ROOT / "ops" / "docker" / "agent-sandbox"


def _context(tmp_path: Path) -> SandboxContext:
    repo = tmp_path / "package-worktree"
    repo.mkdir()
    key = tmp_path / "izo_asa_coding_readonly"
    known_hosts = tmp_path / "known_hosts"
    key.write_text("private-key-fixture\n", encoding="utf-8")
    known_hosts.write_text("github.com fixture\n", encoding="utf-8")
    return SandboxContext(
        repo=repo,
        package_id="STAB-CREDENTIAL-ISOLATION-REPAIR-001",
        base_sha="a" * 40,
        key_path=key,
        known_hosts_path=known_hosts,
    )


def _mount_specs(args: list[str]) -> list[str]:
    return [
        args[index + 1]
        for index, value in enumerate(args)
        if value == "--volume"
    ]


def test_run_args_mount_only_allowed_inputs_and_drop_privileges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sandbox.shutil, "which", lambda _: "docker")
    ctx = _context(tmp_path)
    exact_image = "sha256:" + "1" * 64
    args = run_args(ctx, ["boundary-probe"], image_ref=exact_image)

    assert args[:6] == [
        "docker", "run", "--rm", "--platform", PLATFORM, "--read-only"
    ]
    assert "--cap-drop" in args
    assert args[args.index("--cap-drop") + 1] == "ALL"
    assert "no-new-privileges" in args
    assert "--pids-limit" in args
    assert args[args.index("--pids-limit") + 1] == "256"
    assert "/home/agent:rw,nosuid,nodev,uid=10001,gid=10001,mode=0700,size=64m" in args
    assert "/workspace/.runtime/agent:rw,nosuid,nodev,noexec,uid=10001,gid=10001,mode=0700,size=1m" in args

    mounts = _mount_specs(args)
    assert len(mounts) == 4
    assert any(item.endswith(":/workspace:rw") for item in mounts)
    assert any(item.endswith(":/workspace/.git:ro") for item in mounts)
    assert any(item.endswith(":/run/izo-ssh/id:ro") for item in mounts)
    assert any(item.endswith(":/run/izo-ssh/known_hosts:ro") for item in mounts)

    rendered = "\n".join(args)
    for forbidden in (
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "git-credential-manager",
    ):
        assert forbidden not in rendered
    assert "GH_CONFIG_DIR=/home/agent/.config/gh" in rendered
    assert str(Path.home()) not in rendered or str(ctx.key_path) in rendered
    assert exact_image in args
    assert DEFAULT_IMAGE not in args


def test_build_args_use_pinned_platform_and_tracked_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sandbox.shutil, "which", lambda _: "docker")
    ctx = _context(tmp_path)
    context = ctx.repo / "ops" / "docker" / "agent-sandbox"
    context.mkdir(parents=True)
    (context / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")

    fingerprint = source_fingerprint(ctx)
    args = build_args(ctx)
    assert args == [
        "docker",
        "build",
        "--pull",
        "--platform",
        PLATFORM,
        "--label",
        f"{SOURCE_FINGERPRINT_LABEL}={fingerprint}",
        "--tag",
        DEFAULT_IMAGE,
        str(context),
    ]


def test_source_fingerprint_changes_when_build_context_changes(
    tmp_path: Path,
) -> None:
    ctx = _context(tmp_path)
    context = ctx.repo / "ops" / "docker" / "agent-sandbox"
    context.mkdir(parents=True)
    dockerfile = context / "Dockerfile"
    dockerfile.write_text("FROM scratch\n", encoding="utf-8")

    first = source_fingerprint(ctx)
    assert first == source_fingerprint(ctx)
    dockerfile.write_text("FROM scratch\n# changed\n", encoding="utf-8")
    assert source_fingerprint(ctx) != first


@pytest.mark.parametrize("label_value", ["", "sha256:" + "0" * 64])
def test_mutable_tag_with_missing_or_stale_source_label_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    label_value: str,
) -> None:
    monkeypatch.setattr(sandbox.shutil, "which", lambda _: "docker")
    ctx = _context(tmp_path)
    context = ctx.repo / "ops" / "docker" / "agent-sandbox"
    context.mkdir(parents=True)
    (context / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    labels = {SOURCE_FINGERPRINT_LABEL: label_value} if label_value else {}
    payload = [{"Id": "sha256:" + "2" * 64, "Config": {"Labels": labels}}]
    result = SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
    monkeypatch.setattr(sandbox.subprocess, "run", lambda *args, **kwargs: result)

    with pytest.raises(SandboxError, match="SANDBOX_IMAGE_SOURCE_MISMATCH"):
        _validated_image_id(ctx)


def test_probe_runs_exact_validated_image_id_not_mutable_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sandbox.shutil, "which", lambda _: "docker")
    ctx = _context(tmp_path)
    exact_image = "sha256:" + "3" * 64
    fingerprint = "sha256:" + "4" * 64
    monkeypatch.setattr(
        sandbox, "_validated_image_id", lambda _ctx: (exact_image, fingerprint)
    )
    captured: dict[str, object] = {}

    def fake_run(args: list[str], *, cwd: Path) -> int:
        captured["args"] = args
        captured["cwd"] = cwd
        return 0

    monkeypatch.setattr(sandbox, "_run", fake_run)
    assert sandbox.probe(ctx) == 0
    args = captured["args"]
    assert isinstance(args, list)
    assert exact_image in args
    assert DEFAULT_IMAGE not in args
    assert captured["cwd"] == ctx.repo


def test_run_args_reject_mutable_tag_as_image_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sandbox.shutil, "which", lambda _: "docker")
    ctx = _context(tmp_path)
    with pytest.raises(SandboxError, match="SANDBOX_EXACT_IMAGE_ID_REQUIRED"):
        run_args(ctx, ["boundary-probe"], image_ref=DEFAULT_IMAGE)


def test_resolve_context_reuses_active_package_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "owned-worktree"
    repo.mkdir()
    key = tmp_path / "readonly-key"
    known_hosts = tmp_path / "known_hosts"
    key.write_text("key\n", encoding="utf-8")
    known_hosts.write_text("known\n", encoding="utf-8")

    manifest = SimpleNamespace(
        id="STAB-CREDENTIAL-ISOLATION-REPAIR-001",
        base_sha="b" * 40,
    )
    monkeypatch.setattr(sandbox, "resolve_repo_root", lambda _: repo)
    monkeypatch.setattr(sandbox, "load_registry", lambda _: {"entries": []})
    monkeypatch.setattr(
        sandbox,
        "_assert_owner",
        lambda _repo, _payload: ({}, {}, manifest, repo / "tasks" / "x.toml"),
    )
    monkeypatch.setenv("IZO_AGENT_READONLY_KEY", str(key))
    monkeypatch.setenv("IZO_AGENT_KNOWN_HOSTS", str(known_hosts))

    ctx = resolve_context(repo)
    assert ctx.repo == repo
    assert ctx.package_id == manifest.id
    assert ctx.base_sha == manifest.base_sha
    assert ctx.key_path == key.resolve()
    assert ctx.known_hosts_path == known_hosts.resolve()


def test_resolve_context_fails_without_readonly_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "owned-worktree"
    repo.mkdir()
    manifest = SimpleNamespace(id="TEST-PACKAGE", base_sha="c" * 40)
    monkeypatch.setattr(sandbox, "resolve_repo_root", lambda _: repo)
    monkeypatch.setattr(sandbox, "load_registry", lambda _: {"entries": []})
    monkeypatch.setattr(
        sandbox,
        "_assert_owner",
        lambda _repo, _payload: ({}, {}, manifest, repo / "tasks" / "x.toml"),
    )
    monkeypatch.setenv("IZO_AGENT_READONLY_KEY", str(tmp_path / "missing"))
    monkeypatch.setenv("IZO_AGENT_KNOWN_HOSTS", str(tmp_path / "missing-known"))

    with pytest.raises(SandboxError, match="READONLY_DEPLOY_KEY_MISSING"):
        resolve_context(repo)


def test_dockerfile_pins_base_packages_and_nonroot_user() -> None:
    source = (DOCKER_CONTEXT / "Dockerfile").read_text(encoding="utf-8")
    assert (
        "FROM debian:bookworm-slim@sha256:"
        "88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171"
    ) in source
    for pin in (
        "CA_CERTIFICATES_VERSION=20250419~deb12u1",
        "GIT_VERSION=1:2.39.5-0+deb12u3",
        "OPENSSH_CLIENT_VERSION=1:9.2p1-2+deb12u10",
        "PYTHON3_VERSION=3.11.2-1+b1",
        "PYTHON3_PIP_VERSION=23.0.1+dfsg-1",
        "PYTHON3_VENV_VERSION=3.11.2-1+b1",
    ):
        assert pin in source
    assert "USER 10001:10001" in source
    assert "sed -i 's/\\r$//'" in source
    assert "ENTRYPOINT [\"/usr/local/bin/izo-agent-entrypoint\"]" in source


def test_entrypoint_fails_closed_on_host_credentials() -> None:
    source = (DOCKER_CONTEXT / "entrypoint.sh").read_text(encoding="utf-8")
    assert "GH_TOKEN|GITHUB_TOKEN" in source
    assert "USERPROFILE APPDATA LOCALAPPDATA" in source
    assert "[credential]" in source
    assert "helper =" in source
    assert "core.askPass" not in source
    assert "askPass = /bin/false" in source
    assert "IdentitiesOnly=yes" in source
    assert "StrictHostKeyChecking=yes" in source
    assert 'git_dir="/tmp/izo-agent-git"' in source
    assert "export GIT_WORK_TREE=/workspace" in source
    assert "metadata=ephemeral" in source
    assert "config core.autocrlf true" in source
    assert "config core.filemode false" in source
    assert "config core.symlinks false" in source


def test_boundary_probe_covers_every_required_boundary() -> None:
    source = (DOCKER_CONTEXT / "boundary-probe.sh").read_text(encoding="utf-8")
    for marker in (
        "TOKEN_ENV_ABSENT=PASS",
        "GH_AUTH_UNAVAILABLE=PASS",
        "WINDOWS_CREDENTIAL_STORE_UNREACHABLE=PASS",
        "HTTPS_PRIVATE_ACCESS_DENIED=PASS",
        "SSH_READ_FETCH=PASS",
        "PUSH_MAIN_SERVER_SIDE_DENIED=PASS",
        "PUSH_FEATURE_SERVER_SIDE_DENIED=PASS",
        "SANDBOX_BOUNDARY_OK",
    ):
        assert marker in source
    assert "git -C /tmp -c credential.helper=" in source
    assert "authentication-denial signature" in source
    assert "git push --no-verify --dry-run" not in source
    assert source.count("push --no-verify --dry-run") == 2
    assert "origin HEAD:refs/heads/main" in source
    assert "origin HEAD:refs/heads/agent/credential-isolation-probe" in source
    assert "marked as read only" in source
    assert "git-credential-manager" in source
    assert "/run/desktop/mnt/host/c" in source
    assert "git -C /tmp" in source


def test_run_command_base64_preserves_shell_syntax() -> None:
    command = 'printf "USER=%s\\n" "$(id -u):$(id -g)"; git status --short'
    encoded = base64.b64encode(command.encode("utf-8")).decode("ascii")
    assert resolve_run_command("", encoded) == command
    assert resolve_run_command("sh", "") == "sh"
    with pytest.raises(SandboxError, match="SANDBOX_COMMAND_CONFLICT"):
        resolve_run_command("sh", encoded)
    with pytest.raises(SandboxError, match="SANDBOX_COMMAND_ENCODING_INVALID"):
        resolve_run_command("", "not@base64")


def test_agent_cli_exposes_sandbox_through_canonical_surface() -> None:
    source = (ROOT / "tools" / "agent.ps1").read_text(encoding="utf-8")
    assert '"sandbox"' in source
    assert '"tools.agent_system.sandbox"' in source
    assert '"build", "probe", "run"' in source
    assert "-SandboxAction is required for agent sandbox." in source
    assert "[Convert]::ToBase64String($commandBytes)" in source
    assert '"--command-base64"' in source


def test_quick_verifier_includes_sandbox_contract() -> None:
    source = (ROOT / "tools" / "verify.ps1").read_text(encoding="utf-8")
    assert '"tools/test_agent_sandbox.py"' in source
