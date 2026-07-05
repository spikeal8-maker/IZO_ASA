# ==========================================================================
#  Install IZO_ASA as a Windows scheduled task (auto-start on boot).
#  MUST be run as Administrator from an elevated PowerShell window.
#  Run once, then Windows will launch start-public.bat on every boot.
# ==========================================================================
#Requires -RunAsAdministrator

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSCommandPath
$launcher    = Join-Path $projectRoot "start-public.bat"

if (-not (Test-Path $launcher)) {
    Write-Error "Launcher not found: $launcher"
    exit 1
}

# Remove old task if it exists
Unregister-ScheduledTask -TaskName "IZO_ASA_Public" -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction `
    -Execute $launcher `
    -WorkingDirectory $projectRoot

$trigger = New-ScheduledTaskTrigger -AtStartup

# Run as SYSTEM — starts before user login, has full machine access
$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

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
    -Description "IZO ASA — auto-start backend + frontend on system boot" `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force

Write-Host ''
Write-Host '========================================' -ForegroundColor Green
Write-Host "  Task 'IZO_ASA_Public' INSTALLED"      -ForegroundColor Green
Write-Host '========================================' -ForegroundColor Green
Write-Host ''
Write-Host ('  Launcher : ' + $launcher)
Write-Host '  Run at   : Windows startup (before login)'
Write-Host '  Restarts : up to 3 times on failure (2 min apart)'
Write-Host ''
Write-Host '  Test now : Start-ScheduledTask -TaskName IZO_ASA_Public'
Write-Host '  Remove   : Unregister-ScheduledTask -TaskName IZO_ASA_Public'
Write-Host ''
