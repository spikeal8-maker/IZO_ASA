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
$networkScript = Join-Path $PSScriptRoot 'yandex_network.ps1'
if (-not (Test-Path -LiteralPath $networkScript -PathType Leaf)) {
    throw "Yandex network verifier is unavailable: $networkScript"
}
. $networkScript
$network = Get-IzoYandexNetworkState
if (-not $network.HttpsReachable) { throw 'Yandex.Disk HTTPS connectivity check failed.' }
if ($network.ProbeInterface -match '(?i)AdGuard.*VPN' -and -not $network.AppBypassConfigured) {
    throw 'Yandex.Disk has no verified AdGuard application exclusion; VPN settings were not changed.'
}
if (-not $network.AppBypassObserved) {
    Write-Warning 'Yandex.Disk application exclusion is configured, but process-specific bypass was not observed in recent AdGuard logs.'
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
$retentionTool = Join-Path ([string]$config.active_release) 'tools\prune_backup_snapshots.py'
$retentionReport = Join-Path ([string]$config.log_root) 'retention-cloud-latest.json'
& $config.python $retentionTool `
    --scope cloud `
    --cloud-root $config.cloud_root `
    --report $retentionReport `
    --apply
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
exit 0
