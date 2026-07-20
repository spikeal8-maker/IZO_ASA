[CmdletBinding()]
param([string]$OperationsConfig = 'C:\IZO_ASA\config\backup-operations.json')

$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath $OperationsConfig -Raw -Encoding UTF8 | ConvertFrom-Json
$role = Get-Content -LiteralPath $config.role_config -Raw -Encoding UTF8 | ConvertFrom-Json
$healthPath = [string]$config.health_file
$health = @{}
if (Test-Path -LiteralPath $healthPath) {
    $document = Get-Content -LiteralPath $healthPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($property in $document.PSObject.Properties) { $health[$property.Name] = $property.Value }
}
$errors = [System.Collections.Generic.List[string]]::new()
$now = [DateTimeOffset]::UtcNow

function Test-FreshTimestamp {
    param([object]$Value, [int]$MaximumMinutes, [string]$ErrorCode)
    if (-not $Value) { $errors.Add($ErrorCode); return }
    try {
        if ($Value -is [DateTime]) {
            $timestamp = [DateTimeOffset]::new(([DateTime]$Value).ToUniversalTime())
        } elseif ($Value -is [DateTimeOffset]) {
            $timestamp = [DateTimeOffset]$Value
        } else {
            $timestamp = [DateTimeOffset]::Parse(
                [string]$Value,
                [Globalization.CultureInfo]::InvariantCulture,
                [Globalization.DateTimeStyles]::RoundtripKind
            )
        }
        $age = $now - $timestamp.ToUniversalTime()
    }
    catch { $errors.Add($ErrorCode); return }
    if ($age.TotalMinutes -gt $MaximumMinutes) { $errors.Add($ErrorCode) }
}

$yandexRunning = [bool](Get-Process -Name YandexDisk4 -ErrorAction SilentlyContinue)
$legacyYandexRunning = [bool](Get-Process -Name YandexDisk2 -ErrorAction SilentlyContinue)
$legacyRootConflict = $false
if ($legacyYandexRunning) {
    $legacyRoot = (Get-ItemProperty 'HKCU:\Software\Yandex\Yandex.Disk.2' -ErrorAction SilentlyContinue).RootFolder
    $disk4Root = (Get-ItemProperty 'HKCU:\Software\Yandex\Yandex.Disk.4\*' -ErrorAction SilentlyContinue |
        Where-Object SyncFolder | Select-Object -First 1 -ExpandProperty SyncFolder)
    if ($legacyRoot -and $disk4Root) {
        $legacyFull = [IO.Path]::GetFullPath([string]$legacyRoot).TrimEnd('\')
        $disk4Full = [IO.Path]::GetFullPath([string]$disk4Root).TrimEnd('\')
        $legacyRootConflict = (
            $legacyFull.Equals($disk4Full, [StringComparison]::OrdinalIgnoreCase) -or
            $legacyFull.StartsWith($disk4Full + '\', [StringComparison]::OrdinalIgnoreCase) -or
            $disk4Full.StartsWith($legacyFull + '\', [StringComparison]::OrdinalIgnoreCase)
        )
    }
}
$cloudAvailable = Test-Path -LiteralPath $config.cloud_root -PathType Container
$route = Test-NetConnection disk.yandex.ru -Port 443 -InformationLevel Detailed -WarningAction SilentlyContinue
$routedViaAdguardVpn = [bool]($route.InterfaceAlias -match '(?i)AdGuard.*VPN')
# BACKUP-NET-001 (owner decision 2026-07-20): Yandex Disk is excluded inside
# AdGuard VPN, so the split happens in-tunnel and the interface alias alone
# cannot prove the real path. Compare the egress address Yandex sees with the
# general VPN egress; only a proven split clears the route error (fail-closed
# when either probe is unavailable). Raw addresses are never persisted.
$yandexEgressSplit = $null
if ($routedViaAdguardVpn -and $route.TcpTestSucceeded) {
    $generalEgress = ''
    $yandexEgress = ''
    try { $generalEgress = [string](Invoke-RestMethod 'https://api.ipify.org?format=json' -TimeoutSec 15).ip } catch {}
    try {
        $page = Invoke-WebRequest 'https://yandex.ru/internet' -UseBasicParsing -TimeoutSec 20
        if ($page.Content -match 'IPv4[^\d]*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})') { $yandexEgress = $Matches[1] }
    } catch {}
    if ($generalEgress -and $yandexEgress) { $yandexEgressSplit = ($generalEgress -ne $yandexEgress) }
}
$syncVolumeFreeGB = $null
$syncVolumeFreePercent = $null
if ($cloudAvailable) {
    $root = [IO.Path]::GetPathRoot([string]$config.cloud_root).TrimEnd('\')
    $disk = Get-CimInstance Win32_LogicalDisk -Filter ("DeviceID='$root'")
    if ($disk) {
        $syncVolumeFreeGB = [math]::Round($disk.FreeSpace / 1GB, 2)
        $syncVolumeFreePercent = [math]::Round(100 * $disk.FreeSpace / $disk.Size, 2)
        if ($syncVolumeFreeGB -lt 50) { $errors.Add('sync_volume_free_space_below_50_gb') }
    }
}
if (-not $yandexRunning) { $errors.Add('yandex_disk_not_running') }
if ($legacyRootConflict) { $errors.Add('yandex_sync_roots_overlap') }
if (-not $route.TcpTestSucceeded) { $errors.Add('yandex_https_unavailable') }
if ($routedViaAdguardVpn -and $yandexEgressSplit -ne $true) { $errors.Add('yandex_routed_through_adguard_vpn') }
if ((Get-Service cldflt -ErrorAction SilentlyContinue).Status -ne 'Running') { $errors.Add('cldflt_not_running') }
if (-not $cloudAvailable) { $errors.Add('cloud_folder_unavailable') }

if ($role.role -eq 'PRIMARY') {
    Test-FreshTimestamp $health.LastLocalBackup 120 'local_backup_older_than_2_hours'
    Test-FreshTimestamp $health.LastCloudStage 1560 'cloud_stage_older_than_26_hours'
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
$health['YandexEgressSplitActive'] = $yandexEgressSplit
$health['CloudFreeGB'] = $null
$health['CloudFreePercent'] = $null
$health['SyncVolumeFreeGB'] = $syncVolumeFreeGB
$health['SyncVolumeFreePercent'] = $syncVolumeFreePercent
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
