from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "ops" / "release" / "install-project-promoter.ps1"
PROMOTER = ROOT / "ops" / "release" / "promote-project-release.ps1"
GIT = shutil.which("git")
PWSH = shutil.which("pwsh") or shutil.which("powershell")

pytestmark = pytest.mark.skipif(
    os.name != "nt" or not GIT or not PWSH,
    reason="Windows PowerShell and Git contract",
)


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    release = repo / "ops" / "release"
    release.mkdir(parents=True)
    shutil.copy2(PROMOTER, release / PROMOTER.name)
    shutil.copy2(INSTALLER, release / INSTALLER.name)
    subprocess.run([GIT, "init", "-q", str(repo)], check=True)
    subprocess.run([GIT, "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run([GIT, "-C", str(repo), "config", "user.name", "Promoter Test"], check=True)
    subprocess.run([GIT, "-C", str(repo), "add", "."], check=True)
    subprocess.run([GIT, "-C", str(repo), "commit", "-q", "-m", "fixture"], check=True)
    commit = subprocess.run(
        [GIT, "-C", str(repo), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    return repo, commit


def _run(repo: Path, commit: str, tmp_path: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            PWSH,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(INSTALLER),
            "-RepoRoot",
            str(repo),
            "-ExpectedCommit",
            commit,
            "-DestinationPath",
            str(tmp_path / "runtime" / "promote-project-release.ps1"),
            "-BackupRoot",
            str(tmp_path / "rollback"),
            "-ReceiptPath",
            str(tmp_path / "health" / "promoter-install-current.json"),
            "-GitPath",
            GIT,
            *extra,
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def test_installer_copies_exact_promoter_and_writes_receipt(tmp_path: Path) -> None:
    repo, commit = _repo(tmp_path)
    destination = tmp_path / "runtime" / "promote-project-release.ps1"
    destination.parent.mkdir(parents=True)
    destination.write_text("previous promoter\n", encoding="utf-8")
    result = _run(repo, commit, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PROMOTER_INSTALL_OK" in result.stdout
    installed = destination
    assert installed.read_bytes() == (repo / "ops" / "release" / PROMOTER.name).read_bytes()
    receipt = json.loads(
        (tmp_path / "health" / "promoter-install-current.json").read_text(encoding="utf-8-sig")
    )
    assert receipt["commit"] == commit
    assert receipt["services_restarted"] is False
    assert Path(receipt["previous_backup"]).read_text(encoding="utf-8") == "previous promoter\n"


def test_installer_refuses_dirty_source_tree(tmp_path: Path) -> None:
    repo, commit = _repo(tmp_path)
    (repo / "ops" / "release" / PROMOTER.name).write_text("dirty\n", encoding="utf-8")
    result = _run(repo, commit, tmp_path)

    assert result.returncode != 0
    assert "Tracked working tree changes are present" in result.stderr
    assert not (tmp_path / "runtime" / "promote-project-release.ps1").exists()


def test_installer_plan_only_is_read_only(tmp_path: Path) -> None:
    repo, commit = _repo(tmp_path)
    result = _run(repo, commit, tmp_path, "-PlanOnly")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PROMOTER_INSTALL_PLAN_OK" in result.stdout
    assert not (tmp_path / "runtime").exists()
