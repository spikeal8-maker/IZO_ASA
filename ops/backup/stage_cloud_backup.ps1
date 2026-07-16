[CmdletBinding()]
param(
    [string]$OperationsConfig = 'C:\IZO_ASA\config\backup-operations.json'
)

$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath $OperationsConfig -Raw | ConvertFrom-Json
$role = Get-Content -LiteralPath $config.role_config -Raw | ConvertFrom-Json
if ($role.role -ne 'PRIMARY' -or $role.databaseWriter -ne $true) {
    throw 'Cloud staging is allowed only on PRIMARY.'
}

$yandex = Get-Process -Name YandexDisk4 -ErrorAction SilentlyContinue
if (-not $yandex) { throw 'YandexDisk4.exe is not running.' }
if (Get-Process -Name YandexDisk2 -ErrorAction SilentlyContinue) {
    throw 'Legacy YandexDisk2.exe is running together with Disk 4. Resolve the client conflict before staging.'
}
$route = Test-NetConnection disk.yandex.ru -Port 443 -InformationLevel Detailed -WarningAction SilentlyContinue
if (-not $route.TcpTestSucceeded) { throw 'Yandex.Disk HTTPS connectivity check failed.' }
if ($route.InterfaceAlias -match '(?i)AdGuard.*VPN') { throw 'Yandex.Disk traffic is routed through AdGuard VPN; configure split tunneling first.' }
if (-not (Test-Path -LiteralPath $config.cloud_root -PathType Container)) {
    throw 'Configured Yandex.Disk cloud root is unavailable.'
}

$tool = Join-Path ([string]$config.active_release) 'tools\backup_transport.py'
& $config.python $tool `
    --role-config $config.role_config `
    --health $config.health_file `
    stage --config $config.backup_config --cloud-root $config.cloud_root
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
exit 0
