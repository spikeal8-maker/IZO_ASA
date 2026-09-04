from __future__ import annotations

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
    assert f"STOPPED_BACKEND_RECOVERY_PLAN_OK check={check}" in result.stdout


def test_stopped_backend_recovery_has_fail_closed_evidence() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    for required in (
        "rolled_back",
        "PROMOTION_FAILED",
        "IZOBackend must be a registered stopped service",
        "Port 8000 must be closed",
        "mode=ro",
        "PRAGMA quick_check",
        "currentMax",
        "previousMax",
        "Stopped backend must produce an explicit 502",
    ):
        assert required in source
    for forbidden in ("Start-Service", "Stop-Service", "Set-Content", "Remove-Item"):
        assert forbidden not in source


def test_full_verifier_routes_live_gates_through_recovery_check() -> None:
    source = VERIFY.read_text(encoding="utf-8")

    assert "[switch]$StoppedBackendRecovery" in source
    assert "StoppedBackendRecovery requires Full mode" in source
    for check in ("Backend", "Listeners", "Edge"):
        assert f'"-Check", "{check}"' in source
    assert "stoppedBackendRecovery = [bool]$StoppedBackendRecovery" in source
