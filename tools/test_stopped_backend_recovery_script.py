from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "check-stopped-backend-recovery.ps1"
VERIFY = ROOT / "tools" / "verify.ps1"


def run_powershell_probe(script: str) -> subprocess.CompletedProcess[str]:
    powershell = shutil.which("powershell.exe")
    if not powershell:
        pytest.skip("Windows PowerShell is unavailable")
    env = os.environ.copy()
    env["IZO_TEST_RECOVERY_CHECKER"] = str(SCRIPT)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        env=env, capture_output=True, text=True, errors="replace", timeout=20,
    )


def test_recovery_getfullpath_calls_have_framework_compatible_parsed_arity() -> None:
    result = run_powershell_probe(r"""
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($env:IZO_TEST_RECOVERY_CHECKER,[ref]$tokens,[ref]$errors)
if ($errors.Count) {throw 'Parser errors in recovery checker'}
$calls=$ast.FindAll({param($node) $node -is [Management.Automation.Language.InvokeMemberExpressionAst] -and $node.Member.Extent.Text -eq 'GetFullPath'},$true)
if (-not $calls.Count) {throw 'No calls inspected'}
foreach ($call in $calls) {
    if ($call.Arguments.Count -ne 1) {throw "GetFullPath at line $($call.Extent.StartLineNumber) has $($call.Arguments.Count) parsed arguments"}
}
Write-Output 'GETFULLPATH_ARITY_OK'
""")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "GETFULLPATH_ARITY_OK" in result.stdout


def test_recovery_database_url_conversion_executes_without_database_or_service_access() -> None:
    result = run_powershell_probe(r"""
$ErrorActionPreference='Stop'
# Fail if PlanOnly or conversion starts using live service/database operations.
function Get-Service {throw 'Unexpected service access'}
function Get-CimInstance {throw 'Unexpected service access'}
function Test-Path {throw 'Unexpected filesystem probe'}
function Get-Content {throw 'Unexpected file read'}
function python.exe {throw 'Unexpected database probe'}
. $env:IZO_TEST_RECOVERY_CHECKER -Check Backend -PlanOnly
$cases = @(
    @('sqlite:///F:/synthetic-recovery/active/database.sqlite3', 'F:\synthetic-recovery\active\database.sqlite3'),
    @('sqlite:///C:/synthetic recovery/child/../database.sqlite3', 'C:\synthetic recovery\database.sqlite3'),
    @('sqlite:///F:\synthetic-recovery\database.sqlite3', 'F:\synthetic-recovery\database.sqlite3'),
    @('sqlite:///F:/synthetic/данные/database.sqlite3', 'F:\synthetic\данные\database.sqlite3')
)
foreach ($case in $cases) {
    $actual = Convert-IzoRecoveryDatabasePath -DatabaseUrl $case[0]
    if ($actual -cne $case[1]) {throw 'Synthetic database URL conversion mismatch'}
}
foreach ($invalid in @('', 'postgresql://synthetic/db', 'sqlite://relative.db')) {
    $rejected = $false
    try { $null = Convert-IzoRecoveryDatabasePath -DatabaseUrl $invalid }
    catch {
        if ($_.Exception.Message -ne 'Stopped-backend recovery supports only the installed SQLite topology.') {throw}
        $rejected = $true
    }
    if (-not $rejected) {throw 'Unsupported database URL was accepted'}
}
Write-Output 'DATABASE_URL_CONVERSION_OK databaseOpened=False serviceAccessed=False'
""")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "DATABASE_URL_CONVERSION_OK databaseOpened=False serviceAccessed=False" in result.stdout


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
    assert "databaseUrl=windows-powershell-5.1-compatible" in result.stdout
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
