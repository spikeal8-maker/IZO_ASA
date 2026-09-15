from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tools.agent_system.main_guard import (
    MainGuardError,
    assert_local_mutation_allowed,
    assert_remote_target_allowed,
    check_pre_push_stream,
)

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
INSTALLER = ROOT / "tools" / "install-agent-hooks.ps1"

def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()

def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo with spaces"
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "main-guard@example.invalid")
    _git(repo, "config", "user.name", "Main Guard Test")
    (repo / "README.md").write_text("test\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    return repo

def test_remote_target_guard_rejects_main_and_allows_feature() -> None:
    for target in ("main", "refs/heads/main"):
        with pytest.raises(MainGuardError, match="DIRECT_MAIN_FORBIDDEN"):
            assert_remote_target_allowed(target)
    assert assert_remote_target_allowed("refs/heads/feature/test") == "refs/heads/feature/test"

def test_pre_push_stream_checks_every_remote_ref() -> None:
    safe = "refs/heads/a 1 refs/heads/feature/a 0\nrefs/heads/b 2 refs/heads/feature/b 0\n"
    assert check_pre_push_stream(safe) == 2
    mixed = safe + "refs/heads/main 3 refs/heads/main 1\n"
    with pytest.raises(MainGuardError, match="DIRECT_MAIN_FORBIDDEN"):
        check_pre_push_stream(mixed)
    with pytest.raises(MainGuardError, match="PRE_PUSH_INPUT_INVALID"):
        check_pre_push_stream("broken input\n")

def test_local_mutation_guard_fails_main_and_detached(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    with pytest.raises(MainGuardError, match="DIRECT_MAIN_FORBIDDEN"):
        assert_local_mutation_allowed(repo)
    _git(repo, "switch", "-c", "feature/safe")
    assert assert_local_mutation_allowed(repo) == "feature/safe"
    _git(repo, "checkout", "--detach", "HEAD")
    with pytest.raises(MainGuardError, match="detached-or-ambiguous"):
        assert_local_mutation_allowed(repo)

def test_agent_cli_exposes_main_guard() -> None:
    feature = subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "tools" / "agent.ps1"), "main-guard", "-Ref", "refs/heads/feature/safe"],
        text=True, capture_output=True, timeout=60, check=False,
    )
    assert feature.returncode == 0, feature.stdout + feature.stderr
    assert "MAIN_GUARD_OK" in feature.stdout
    main = subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "tools" / "agent.ps1"), "main-guard", "-Ref", "refs/heads/main"],
        text=True, capture_output=True, timeout=60, check=False,
    )
    assert main.returncode != 0
    assert "DIRECT_MAIN_FORBIDDEN" in main.stderr

@pytest.mark.skipif(not POWERSHELL.exists(), reason="hook installer contract is Windows-specific")
def test_hook_installer_is_repo_local_and_idempotent(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    shutil.copytree(ROOT / ".githooks", repo / ".githooks")
    command = [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(INSTALLER), "-RepoRoot", str(repo)]
    for _ in range(2):
        result = subprocess.run(command, text=True, capture_output=True, timeout=60, check=False)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "AGENT_HOOKS_INSTALLED" in result.stdout
    assert _git(repo, "config", "--local", "--get", "core.hooksPath") == ".githooks"

def test_versioned_hooks_delegate_to_canonical_guard() -> None:
    pre_push = (ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
    pre_commit = (ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
    assert "tools/agent_system/main_guard.py" in pre_push
    assert " pre-push" in pre_push
    assert "tools/agent_system/main_guard.py" in pre_commit
    assert " check-local" in pre_commit
    assert "--no-verify" not in pre_push + pre_commit

@pytest.mark.skipif(not POWERSHELL.exists(), reason="hook installer contract is Windows-specific")
def test_hook_installer_refuses_existing_hooks_path(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    shutil.copytree(ROOT / ".githooks", repo / ".githooks")
    _git(repo, "config", "--local", "core.hooksPath", ".custom-hooks")
    result = subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(INSTALLER), "-RepoRoot", str(repo)],
        text=True, capture_output=True, timeout=60, check=False,
    )
    assert result.returncode != 0
    assert "AGENT_HOOKS_PATH_CONFLICT" in result.stderr
    assert _git(repo, "config", "--local", "--get", "core.hooksPath") == ".custom-hooks"
