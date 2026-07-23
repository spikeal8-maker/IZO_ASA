from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WATCHDOG = ROOT / "ops" / "windows" / "comfyui-image-watchdog.ps1"
INSTALLER = ROOT / "ops" / "windows" / "install-comfyui-image-watchdog.ps1"


def test_watchdog_is_fixed_to_comfyui_and_keeps_request_until_recovery() -> None:
    script = WATCHDOG.read_text(encoding="utf-8")
    assert "Restart-Service -Name $ServiceName -Force" in script
    assert "image-generation-watchdog" in script
    assert "Remove-Item -LiteralPath $resolvedRequest -Force" in script
    assert script.index("EndpointReady = $true") < script.index(
        "Remove-Item -LiteralPath $resolvedRequest -Force"
    )
    assert "Invoke-Expression" not in script


def test_installer_runs_as_system_and_grants_backend_only_runtime_modify() -> None:
    script = INSTALLER.read_text(encoding="utf-8")
    assert "New-ScheduledTaskPrincipal -UserId 'SYSTEM'" in script
    assert "'NT AUTHORITY\\LOCAL SERVICE:(OI)(CI)(M)'" in script
    assert "-MultipleInstances IgnoreNew" in script
    assert "comfyui-image-watchdog.ps1" in script
