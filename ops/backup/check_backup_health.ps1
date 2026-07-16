[CmdletBinding()]
param([string]$OperationsConfig = 'C:\IZO_ASA\config\backup-operations.json')

$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath $OperationsConfig -Raw | ConvertFrom-Json
$role = Get-Content -LiteralPath $config.role_config -Raw | ConvertFrom-Json
$healthPath = [string]$config.health_file
$health = @{}
if (Test-Path -LiteralPath $healthPath) {
    $document = Get-Content -LiteralPath $healthPath -Raw | ConvertFrom-Json
    foreach ($property in $document.PSObject.Properties) { $health[$property.Name] = $property.Value }
}
$errors = [System.Collections.Generic.List[string]]::new()
$now = [DateTimeOffset]::UtcNow

function Test-FreshTimestamp {
    param([object]$Value, [int]$MaximumMinutes, [string]$ErrorCode)
    if (-not $Value) { $errors.Add($ErrorCode); return }
    try { $age = $now - [DateTimeOffset]::Parse([string]$Value) }
    catch { $errors.Add($ErrorCode); return }
    if ($age.TotalMinutes -gt $MaximumMinutes) { $errors.Add($ErrorCode) }
}

$yandexRunning = [bool](Get-Process -Name YandexDisk4 -ErrorAction SilentlyContinue)
$legacyYandexRunning = [bool](Get-Process -Name YandexDisk2 -ErrorAction SilentlyContinue)
$cloudAvailable = Test-Path -LiteralPath $config.cloud_root -PathType Container
$route = Test-NetConnection disk.yandex.ru -Port 443 -InformationLevel Detailed -WarningAction SilentlyContinue
$cloudFreeGB = $null
$cloudFreePercent = $null
if ($cloudAvailable) {
    $root = [IO.Path]::GetPathRoot([string]$config.cloud_root).TrimEnd('\')
    $disk = Get-CimInstance Win32_LogicalDisk -Filter ("DeviceID='$root'")
    if ($disk) {
        $cloudFreeGB = [math]::Round($disk.FreeSpace / 1GB, 2)
        $cloudFreePercent = [math]::Round(100 * $disk.FreeSpace / $disk.Size, 2)
        if ($cloudFreePercent -lt 15) { $errors.Add('cloud_free_space_below_15_percent') }
    }
}
if (-not $yandexRunning) { $errors.Add('yandex_disk_not_running') }
if ($legacyYandexRunning) { $errors.Add('legacy_yandex_disk_running') }
if (-not $route.TcpTestSucceeded) { $errors.Add('yandex_https_unavailable') }
if ($route.InterfaceAlias -match '(?i)AdGuard.*VPN') { $errors.Add('yandex_routed_through_adguard_vpn') }
if ((Get-Service cldflt -ErrorAction SilentlyContinue).Status -ne 'Running') { $errors.Add('cldflt_not_running') }
if (-not $cloudAvailable) { $errors.Add('cloud_folder_unavailable') }

if ($role.role -eq 'PRIMARY') {
    Test-FreshTimestamp $health.LastLocalBackup 30 'local_backup_older_than_30_minutes'
    Test-FreshTimestamp $health.LastCloudStage 90 'cloud_stage_older_than_90_minutes'
} elseif ($role.role -eq 'STANDBY') {
    Test-FreshTimestamp $health.LastReplicaReceive 120 'replica_older_than_120_minutes'
} else {
    $errors.Add('server_role_invalid')
}

$health['YandexDiskRunning'] = $yandexRunning
$health['LegacyYandexDiskRunning'] = $legacyYandexRunning
$health['YandexSyncErrors'] = @($errors)
$health['CloudFolderAvailable'] = $cloudAvailable
$health['YandexRouteInterface'] = [string]$route.InterfaceAlias
$health['YandexHttpsReachable'] = [bool]$route.TcpTestSucceeded
$health['CloudFreeGB'] = $cloudFreeGB
$health['CloudFreePercent'] = $cloudFreePercent
$health['CloudStatus'] = if ($cloudAvailable -and $yandexRunning) { 'AVAILABLE' } else { 'UNAVAILABLE' }
$health['OverallStatus'] = if ($errors.Count -eq 0) { 'OK' } else { 'ATTENTION' }
$health['UpdatedAt'] = $now.ToString('o')
$temporary = "$healthPath.tmp"
[IO.File]::WriteAllText($temporary, ($health | ConvertTo-Json -Depth 8) + "`n", [Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $temporary -Destination $healthPath -Force

if ($errors.Count -gt 0) {
    Write-Host ("BACKUP_HEALTH_ATTENTION errors=" + ($errors -join ','))
    exit 2
}
Write-Host 'BACKUP_HEALTH_OK'
exit 0
