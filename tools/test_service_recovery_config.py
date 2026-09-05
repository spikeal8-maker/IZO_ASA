from __future__ import annotations

import base64
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_native_reader_uses_query_only_service_access() -> None:
    source = (ROOT / "ops/release/service-recovery-config.ps1").read_text(encoding="utf-8")
    guard = (ROOT / "ops/release/recovery-service-guard.ps1").read_text(encoding="utf-8")
    assert "OpenService(manager, name, 1)" in source
    assert "QueryServiceConfig2(service, 2," in source
    assert "CloseServiceHandle(service)" in source
    assert "Marshal.FreeHGlobal(buffer)" in source
    assert "qfailure" not in source + guard
    for forbidden in ("ChangeServiceConfig", "StartService", "ControlService", "Set-ItemProperty"):
        assert forbidden not in source


def test_native_reader_executes_on_windows_powershell_51() -> None:
    powershell = shutil.which("powershell.exe")
    if not powershell:
        pytest.skip("Windows PowerShell is unavailable")
    script = r"""
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. $env:IZO_TEST_READER
# Query only the standard OS EventLog service, never an application service.
# This exercises real ABI/layout/handles without changing service configuration.
$delays=@(Get-IzoServiceRecoveryDelays -ServiceName 'EventLog')
foreach ($delay in $delays) { if ($delay -isnot [uint32]) {throw 'Expected native DWORD delay'} }
$missingRejected=$false
try { $null=Get-IzoServiceRecoveryDelays -ServiceName 'IZO_Missing_Test_Service_6df83d4e' }
catch {
    $exception=$_.Exception
    while ($null -ne $exception.InnerException) {$exception=$exception.InnerException}
    if ($exception -isnot [ComponentModel.Win32Exception] -or $exception.NativeErrorCode -ne 1060) {throw}
    $missingRejected=$true
}
if (-not $missingRejected) {throw 'Missing service did not fail closed'}
# Repeat after an exception to exercise handle cleanup and loaded-type reuse.
$null=Get-IzoServiceRecoveryDelays -ServiceName 'EventLog'
Write-Output 'NATIVE_CONFIG_READ_OK'
"""
    env = os.environ.copy()
    env["IZO_TEST_READER"] = str(ROOT / "ops/release/service-recovery-config.ps1")
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        env=env, capture_output=True, text=True, errors="replace", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NATIVE_CONFIG_READ_OK" in result.stdout
