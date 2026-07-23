param(
    [string]$TaskName = 'IZO_ASA ComfyUI Image Watchdog'
)

$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'comfyui-image-watchdog.ps1'
$runtimeDirectory = 'C:\IZO_ASA\runtime\comfyui-watchdog'
$runtimeScript = Join-Path $runtimeDirectory 'comfyui-image-watchdog.ps1'
$requestPath = Join-Path $runtimeDirectory 'request.json'
$healthPath = 'C:\IZO_ASA\health\comfyui-watchdog-current.json'

New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
Copy-Item -LiteralPath $source -Destination $runtimeScript -Force
& icacls.exe $runtimeDirectory /inheritance:r /grant:r `
    'SYSTEM:(OI)(CI)(F)' `
    'BUILTIN\Administrators:(OI)(CI)(F)' `
    'NT AUTHORITY\LOCAL SERVICE:(OI)(CI)(M)' | Out-Null

$arguments = @(
    '-NoProfile'
    '-NonInteractive'
    '-WindowStyle', 'Hidden'
    '-ExecutionPolicy', 'Bypass'
    '-File', "`"$runtimeScript`""
    '-RequestPath', "`"$requestPath`""
    '-HealthPath', "`"$healthPath`""
) -join ' '
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Output "Installed $TaskName"
