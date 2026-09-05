from __future__ import annotations

import base64
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "ops/release/recovery-service-guard.ps1"

# Execute the real guard in Windows PowerShell 5.1, replacing service/SCM/lock
# adapters. Every path is under tmp_path; no production service or data is used.
HARNESS = r"""
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. $env:IZO_TEST_GUARD
$testRoot=$env:IZO_TEST_ROOT
$testFlag=Join-Path $testRoot 'maintenance.flag'
$testJournal=Join-Path $testRoot 'guard.json'
$testSha='a'*40
$script:events=[Collections.Generic.List[string]]::new()
$script:state=[pscustomobject]@{Name='IZOBackend';State='Running';Status='Running';ProcessId=42;StartMode='Auto';DelayedAutoStart=$false;PathName='"C:\IZO_ASA\runtime\services\backend\IZOBackend.exe"'}
$script:lockOwner=[pscustomobject]@{owner_pid=$PID;owner_process_start_utc='2026-09-05T00:00:00Z';operation_id='test-operation'}
$script:stale=$false
$script:failStop=$false
$script:failRestore=$false
function Assert-IzoRecoveryAdministrator {}
function Get-IzoRepositoryLockPath { param($RepoRoot,$Kind) return (Join-Path $RepoRoot $Kind) }
function Get-IzoRepositoryLockOwner { param($LockPath) return $script:lockOwner }
function Test-IzoRepositoryLockStale { param($Owner) return $script:stale }
function Get-CimInstance { param($ClassName,$Filter,$ErrorAction) if($Filter -ne "Name='IZOBackend'"){throw 'unexpected service query'}; return $script:state }
function Get-Service { param($Name,$ErrorAction) if($Name -ne 'IZOBackend'){throw 'unexpected service'}; return $script:state }
function Get-NetTCPConnection { param($State,$LocalPort,$ErrorAction) if($LocalPort -ne 8000){throw 'unexpected port'} }
function sc.exe {
    param($Command,$Name,$Option,$Value)
    if($Name -ne 'IZOBackend'){throw 'unexpected SCM service'}
    $global:LASTEXITCODE=0
    if($Command -eq 'qfailure'){return 'RESTART -- Delay = 120000 milliseconds.'}
    if($Command -ne 'config' -or $Option -ne 'start=' -or $Value -notin @('auto','delayed-auto')){throw 'unexpected SCM command'}
    if($script:failRestore){throw 'injected restore failure'}
    $script:events.Add("restore:$Value")
    $script:state.StartMode='Auto'
    $script:state.DelayedAutoStart=($Value -eq 'delayed-auto')
}
function Set-Service {
    param($Name,$StartupType,$ErrorAction)
    if($Name -ne 'IZOBackend'){throw 'unexpected service mutation'}
    if(-not (Test-Path -LiteralPath $testFlag)){throw 'missing maintenance before mutation'}
    if(-not (Test-Path -LiteralPath $testJournal)){throw 'missing journal before mutation'}
    if($StartupType -eq 'Automatic' -and $script:failRestore){throw 'injected restore failure'}
    $script:events.Add("startup:$StartupType")
    $script:state.StartMode=if($StartupType -eq 'Automatic'){'Auto'}else{[string]$StartupType}
}
function Stop-Service {
    param($Name,[switch]$Force,$ErrorAction)
    if($script:state.StartMode -ne 'Disabled'){throw 'SCM restart race: stop before disabling'}
    $script:events.Add('stop')
    if($script:failStop){throw 'injected stop failure'}
    $script:state.State='Stopped';$script:state.Status='Stopped';$script:state.ProcessId=0
}
function New-TestGuard { New-IzoRecoveryServiceGuard -RepoRoot $testRoot -ExpectedSha $testSha -JournalPath $testJournal -MaintenancePath $testFlag }
function Assert-True { param($Value,$Message) if(-not $Value){throw $Message} }
function Assert-Throws { param([scriptblock]$Action,[string]$Pattern) try { & $Action } catch { if($_.Exception.Message -notlike $Pattern){throw}; return }; throw "Expected failure: $Pattern" }
"""


def run_guard(tmp_path: Path, body: str) -> None:
    powershell = shutil.which("powershell.exe")
    if not powershell:
        pytest.skip("Windows PowerShell is unavailable")
    env = os.environ.copy()
    env.update(IZO_TEST_GUARD=str(GUARD), IZO_TEST_ROOT=str(tmp_path))
    script = HARNESS + "\n" + body + "\nWrite-Output 'GUARD_TEST_OK'"
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        env=env, capture_output=True, text=True, errors="replace", timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "GUARD_TEST_OK" in result.stdout


def test_hold_blocks_late_scm_restart_and_hands_off_with_maintenance(tmp_path: Path) -> None:
    run_guard(tmp_path, r"""
$g=New-TestGuard
Suspend-IzoRecoveryBackend -Guard $g
foreach($restartDelay in @(10,30,120)) {
    # SCM cannot start a Disabled service when its previously queued action fires.
    if($script:state.StartMode -ne 'Disabled'){$script:state.State='Running';$script:state.ProcessId=99}
    $null=Assert-IzoRecoveryMaintenance -RepoRoot $testRoot -ExpectedSha $testSha -MaintenancePath $testFlag -RequireStopped
}
Assert-True (($script:events -join ',') -eq 'startup:Disabled,stop') 'must disable then stop exactly once'
Assert-True ($g.DrainSeconds -eq 130) 'must account for longest SCM delay'
$g.DisabledAtUtc=[datetime]::UtcNow.AddMinutes(-20).ToString('o')
Restore-IzoRecoveryStartup -Guard $g -ForPromotion
Assert-True ($script:state.StartMode -eq 'Auto' -and $g.PromotionHandedOff) 'startup not restored for promoter'
Assert-True (Test-Path -LiteralPath $testFlag) 'maintenance gap before promoter'
Close-IzoRecoveryServiceGuard -Guard $g
Assert-True (-not (Test-Path -LiteralPath $testFlag)) 'owned flag was not removed'
Assert-True (Test-Path -LiteralPath $testJournal) 'journal was removed'
""")


def test_failed_stop_restores_original_startup_and_cleans_owned_flag(tmp_path: Path) -> None:
    run_guard(tmp_path, r"""
$g=New-TestGuard
$script:failStop=$true
Assert-Throws {Suspend-IzoRecoveryBackend -Guard $g} '*injected stop failure*'
Close-IzoRecoveryServiceGuard -Guard $g
Assert-True ($script:state.StartMode -eq 'Auto') 'failure left backend Disabled'
Assert-True (-not (Test-Path -LiteralPath $testFlag)) 'failure left maintenance flag'
""")


@pytest.mark.parametrize("violation", ["stale", "foreign_pid", "wrong_exe", "unknown_delay", "foreign_flag"])
def test_rejects_unowned_or_unexpected_configuration_before_mutation(tmp_path: Path, violation: str) -> None:
    setup = {
        "stale": "$script:stale=$true",
        "foreign_pid": "$script:lockOwner.owner_pid=$PID+1",
        "wrong_exe": "$script:state.PathName='C:\\elsewhere\\backend.exe'",
        "unknown_delay": "$script:state.DelayedAutoStart=$null",
        "foreign_flag": "Set-Content -LiteralPath $testFlag -Value 'foreign-owner'",
    }[violation]
    run_guard(tmp_path, setup + r"""
Assert-Throws {New-TestGuard} '*'
Assert-True ($script:events.Count -eq 0) 'rejected guard mutated service'
Assert-True ($script:state.StartMode -eq 'Auto') 'rejected guard changed startup'
""")


def test_restore_failure_keeps_maintenance_and_journal_for_operator(tmp_path: Path) -> None:
    run_guard(tmp_path, r"""
$g=New-TestGuard
Suspend-IzoRecoveryBackend -Guard $g
$script:failRestore=$true
Assert-Throws {Close-IzoRecoveryServiceGuard -Guard $g} '*injected restore failure*'
Assert-True (Test-Path -LiteralPath $testFlag) 'restore failure erased maintenance evidence'
Assert-True (Test-Path -LiteralPath $testJournal) 'restore failure erased journal'
""")


@pytest.mark.parametrize("fail_stop", [False, True])
def test_preserves_installed_delayed_automatic_start(tmp_path: Path, fail_stop: bool) -> None:
    run_guard(tmp_path, r"""
$script:state.DelayedAutoStart=$true
$g=New-TestGuard
Assert-True $g.OriginalDelayedAutoStart 'delayed startup was not journaled'
""" + (r"""
$script:failStop=$true
Assert-Throws {Suspend-IzoRecoveryBackend -Guard $g} '*injected stop failure*'
""" if fail_stop else "Suspend-IzoRecoveryBackend -Guard $g\n") + r"""
# Model loss of the setting while Disabled; restoration must reapply it.
$script:state.DelayedAutoStart=$false
Close-IzoRecoveryServiceGuard -Guard $g
Assert-True ($script:state.StartMode -eq 'Auto' -and $script:state.DelayedAutoStart) 'delayed Automatic was not restored'
Assert-True ($script:events.Contains('restore:delayed-auto')) 'did not explicitly restore delayed Automatic'
Assert-True (-not (Test-Path -LiteralPath $testFlag)) 'left maintenance after restoring startup'
""")


def test_live_check_rejects_pid_restart_or_wrong_source(tmp_path: Path) -> None:
    run_guard(tmp_path, r"""
$g=New-TestGuard
Suspend-IzoRecoveryBackend -Guard $g
$script:state.ProcessId=99
Assert-Throws {Assert-IzoRecoveryMaintenance -RepoRoot $testRoot -ExpectedSha $testSha -MaintenancePath $testFlag -RequireStopped} '*PID zero*'
$script:state.ProcessId=0
Assert-Throws {Assert-IzoRecoveryMaintenance -RepoRoot $testRoot -ExpectedSha ('b'*40) -MaintenancePath $testFlag} '*unexpected identity*'
Close-IzoRecoveryServiceGuard -Guard $g
""")


def test_successful_promoter_can_consume_flag_before_cleanup(tmp_path: Path) -> None:
    run_guard(tmp_path, r"""
$g=New-TestGuard
Suspend-IzoRecoveryBackend -Guard $g
$g.DisabledAtUtc=[datetime]::UtcNow.AddMinutes(-20).ToString('o')
Restore-IzoRecoveryStartup -Guard $g -ForPromotion
# Installed promoter takes over maintenance and removes it in its finally.
Remove-Item -LiteralPath $testFlag
$script:state.State='Running';$script:state.ProcessId=55
Close-IzoRecoveryServiceGuard -Guard $g
Assert-True ($g.PromotionHandedOff -and $g.StartupRestored) 'lost handoff evidence'
Assert-True ($script:state.State -eq 'Running') 'cleanup disturbed the installed release'
""")


def test_foreign_maintenance_after_handoff_is_preserved(tmp_path: Path) -> None:
    run_guard(tmp_path, r"""
$g=New-TestGuard
Suspend-IzoRecoveryBackend -Guard $g
$g.DisabledAtUtc=[datetime]::UtcNow.AddMinutes(-20).ToString('o')
Restore-IzoRecoveryStartup -Guard $g -ForPromotion
Set-Content -LiteralPath $testFlag -Value '{"ProcessId":1234}'
Assert-Throws {Close-IzoRecoveryServiceGuard -Guard $g} '*ownership changed*'
Assert-True (Test-Path -LiteralPath $testFlag) 'foreign maintenance was removed'
""")
