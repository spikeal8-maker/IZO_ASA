[CmdletBinding()]
param(
    [string]$OperationsConfig = 'C:\IZO_ASA\config\backup-operations.json',
    [switch]$Rehearse
)

$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath $OperationsConfig -Raw | ConvertFrom-Json
$role = Get-Content -LiteralPath $config.role_config -Raw | ConvertFrom-Json
if ($role.role -ne 'STANDBY' -or $role.databaseWriter -ne $false) {
    throw 'Replica receive is allowed only on STANDBY with databaseWriter=false.'
}
if (-not (Test-Path -LiteralPath $config.cloud_root -PathType Container)) {
    throw 'Configured Yandex.Disk cloud root is unavailable.'
}

$tool = Join-Path ([string]$config.active_release) 'tools\backup_transport.py'
$arguments = @(
    $tool, '--role-config', [string]$config.role_config,
    '--health', [string]$config.health_file,
    'receive', '--cloud-root', [string]$config.cloud_root,
    '--cache-root', [string]$config.replica_cache
)
if ($Rehearse) {
    $arguments += @('--rehearse', '--work-root', [string]$config.rehearsal_root)
}
& $config.python @arguments
exit $LASTEXITCODE
