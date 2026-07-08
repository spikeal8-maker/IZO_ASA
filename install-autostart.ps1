#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$bat  = Join-Path $root "start-public.bat"

if (-not (Test-Path $bat)) {
    Write-Error "Launcher not found: $bat"
    exit 1
}

Unregister-ScheduledTask -TaskName "IZO_ASA_Public" -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName "IZO_ASA_Public" `
    -Description "IZO ASA auto-start on boot" `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force

Write-Host "Task IZO_ASA_Public installed. Starts on boot, restarts 3x on failure."
Write-Host "Launcher: $bat"
