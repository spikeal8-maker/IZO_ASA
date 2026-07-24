[CmdletBinding()]
param(
    [string]$TaskName = "IZO_ASA Local LTX ComfyUI",
    [string]$RuntimeLauncher = "C:\IZO_ASA\runtime\start-local-ltx-comfyui.ps1"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $RuntimeLauncher -PathType Leaf)) {
    throw "Runtime LTX launcher not found: $RuntimeLauncher"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$RuntimeLauncher`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Supervises the isolated low-VRAM ComfyUI runtime for local LTX 2.3 video generation." `
    -Force | Out-Null

Write-Host "LTX23_TASK_INSTALLED name=$TaskName launcher=$RuntimeLauncher"
