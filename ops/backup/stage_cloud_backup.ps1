[CmdletBinding()]
param(
    [string]$OperationsConfig = 'C:\IZO_ASA\config\backup-operations.json'
)

$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath $OperationsConfig -Raw -Encoding UTF8 | ConvertFrom-Json
$role = Get-Content -LiteralPath $config.role_config -Raw -Encoding UTF8 | ConvertFrom-Json
if ($role.role -ne 'PRIMARY' -or $role.databaseWriter -ne $true) {
    throw 'Cloud staging is allowed only on PRIMARY.'
}

$yandex = Get-Process -Name YandexDisk4 -ErrorAction SilentlyContinue
if (-not $yandex) { throw 'YandexDisk4.exe is not running.' }
if (Get-Process -Name YandexDisk2 -ErrorAction SilentlyContinue) {
    $legacyRoot = (Get-ItemProperty 'HKCU:\Software\Yandex\Yandex.Disk.2' -ErrorAction SilentlyContinue).RootFolder
    $disk4Root = (Get-ItemProperty 'HKCU:\Software\Yandex\Yandex.Disk.4\*' -ErrorAction SilentlyContinue |
        Where-Object SyncFolder | Select-Object -First 1 -ExpandProperty SyncFolder)
    if ($legacyRoot -and $disk4Root) {
        $legacyFull = [IO.Path]::GetFullPath([string]$legacyRoot).TrimEnd('\')
        $disk4Full = [IO.Path]::GetFullPath([string]$disk4Root).TrimEnd('\')
        if ($legacyFull.Equals($disk4Full, [StringComparison]::OrdinalIgnoreCase) -or
            $legacyFull.StartsWith($disk4Full + '\', [StringComparison]::OrdinalIgnoreCase) -or
            $disk4Full.StartsWith($legacyFull + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Yandex Disk 3.x and 4.x sync roots overlap. Resolve the client conflict before staging.'
        }
    }
}
$route = Test-NetConnection disk.yandex.ru -Port 443 -InformationLevel Detailed -WarningAction SilentlyContinue
if (-not $route.TcpTestSucceeded) { throw 'Yandex.Disk HTTPS connectivity check failed.' }
if ($route.InterfaceAlias -match '(?i)AdGuard.*VPN') {
    Write-Warning 'Yandex.Disk traffic is routed through AdGuard VPN. Snapshot staging continues, but health remains ATTENTION until split tunneling is configured.'
}
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
