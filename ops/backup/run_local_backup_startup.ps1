[CmdletBinding()]
param(
    [ValidateRange(0, 3600)]
    [int]$DelaySeconds = 300,
    [string]$OperationsConfig = 'C:\IZO_ASA\config\backup-operations.json'
)

$ErrorActionPreference = 'Stop'
if ($DelaySeconds -gt 0) {
    Start-Sleep -Seconds $DelaySeconds
}

$backupScript = Join-Path $PSScriptRoot 'run_local_backup.ps1'
& $backupScript -OperationsConfig $OperationsConfig
