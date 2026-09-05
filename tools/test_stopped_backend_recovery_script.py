from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "check-stopped-backend-recovery.ps1"
VERIFY = ROOT / "tools" / "verify.ps1"


@pytest.mark.parametrize("check", ["Backend", "Listeners", "Edge"])
def test_stopped_backend_recovery_plan_is_explicit_and_read_only(check: str) -> None:
    powershell = shutil.which("powershell.exe")
    if not powershell:
        pytest.skip("Windows PowerShell is unavailable")

    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-RepoRoot",
            str(ROOT),
            "-Check",
            check,
            "-PlanOnly",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "pathComparison=windows-powershell-5.1-compatible" in result.stdout
    assert f"STOPPED_BACKEND_RECOVERY_PLAN_OK check={check}" in result.stdout


def test_stopped_backend_recovery_has_fail_closed_evidence() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "function Test-IzoNormalizedPathEquals" in source
    assert "function Test-IzoNormalizedPathWithin" in source
    assert 'Assert-IzoRecoveryMaintenance' in source
    assert '-MaintenancePath $maintenanceFlagPath -RequireStopped' in source
    assert not re.search(
        r"\[IO\.Path\]::GetFullPath\([^\r\n]*\)\.(?:Equals|StartsWith)\(",
        source,
    )
    for required in (
        "rolled_back",
        "PROMOTION_FAILED",
        "PROMOTION_PENDING",
        "pending-release-promotion.json",
        "Pending corrective candidate is not bound to a distinct exact SHA and successful CI",
        "Pending corrective candidate is not the current exact source or its canonical ancestor",
        "Pending corrective candidate marker does not match updater evidence",
        "Pending corrective candidate checkout has an unexpected Git HEAD",
        "Pending corrective candidate checkout has an unexpected Git origin",
        "Pending corrective candidate checkout has tracked or untracked changes",
        "update=$updateStatus",
        "IZOBackend must be a registered stopped service",
        "Port 8000 must be closed",
        "mode=ro",
        "PRAGMA quick_check",
        "ledger_matches_definitions",
        "currentMin",
        "currentMax",
        "previousMax",
        "already-failed candidate",
        "AllowStoppedInstalledBackend",
        "Global runtime listener validation failed",
        "Get-IzoFrontendListenerState",
        "ParentProcessId",
        "'/chat'",
        "izo-release",
        "Stopped backend must produce an explicit 502",
    ):
        assert required in source
    assert "'/feed'" not in source
    assert "'/gallery'" not in source
    assert "$currentHead -eq [string]$promotion.NewSha" in source
    assert "git.exe -C $root merge-base --is-ancestor $pendingSha $currentHead" in source
    assert "[string]$update.ActiveSha -ne $oldSha" in source
    assert "[string]$update.CiStatus -ne 'success'" in source
    assert "Test-IzoNormalizedPathEquals -Left ([string]$update.CandidatePath)" in source
    for forbidden in ("Start-Service", "Stop-Service", "Set-Content", "Remove-Item"):
        assert forbidden not in source


def test_full_verifier_routes_live_gates_through_recovery_check() -> None:
    source = VERIFY.read_text(encoding="utf-8")

    assert "[switch]$StoppedBackendRecovery" in source
    assert "StoppedBackendRecovery requires Full mode" in source
    for check in ("Backend", "Listeners", "Edge"):
        assert f'"-Check", "{check}"' in source
    assert "stoppedBackendRecovery = [bool]$StoppedBackendRecovery" in source
