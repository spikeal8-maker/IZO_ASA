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
$localNow = Get-Date
$isPrimary = $role.role -eq 'PRIMARY'
$syncWindowStart = $localNow.Date.AddHours($(if ($isPrimary) { 2 } else { 3 }))
$syncWindowEnd = $localNow.Date.AddHours(5)
$syncWindowActive = $localNow -ge $syncWindowStart -and $localNow -lt $syncWindowEnd
$nightlyTaskName = if ($isPrimary) { 'IZO_ASA Yandex Outbound Nightly' } else { 'IZO_ASA Replica Receive Hourly' }
$nightlyTask = Get-ScheduledTask -TaskName $nightlyTaskName -ErrorAction SilentlyContinue
$nightlyTaskRunning = $null -ne $nightlyTask -and [string]$nightlyTask.State -eq 'Running'
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
$network = $null
if ($yandexRunning) {
    $networkScript = Join-Path $PSScriptRoot 'yandex_network.ps1'
    if (Test-Path -LiteralPath $networkScript -PathType Leaf) {
        . $networkScript
        $network = Get-IzoYandexNetworkState
    } else {
        $errors.Add('yandex_network_verifier_missing')
    }
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
if ($syncWindowActive -and $nightlyTaskRunning -and -not $yandexRunning) {
    $errors.Add('yandex_disk_not_running_during_nightly_window')
}
if (-not $syncWindowActive -and $yandexRunning) {
    $errors.Add('yandex_disk_running_outside_nightly_window')
}
if ($legacyRootConflict) { $errors.Add('yandex_sync_roots_overlap') }
if ($null -ne $network) {
    if (-not $network.HttpsReachable) { $errors.Add('yandex_https_unavailable') }
    if ($network.ProbeInterface -match '(?i)AdGuard.*VPN' -and -not $network.AppBypassConfigured) {
        $errors.Add('yandex_adguard_app_exclusion_missing')
    }
}
if ((Get-Service cldflt -ErrorAction SilentlyContinue).Status -ne 'Running') { $errors.Add('cldflt_not_running') }
if (-not $cloudAvailable) { $errors.Add('cloud_folder_unavailable') }

if ($role.role -eq 'PRIMARY') {
    Test-FreshTimestamp $health.LastLocalBackup 45 'local_backup_older_than_45_minutes'
    Test-FreshTimestamp $health.LastCloudStage 1800 'cloud_stage_older_than_30_hours'
} elseif ($role.role -eq 'STANDBY') {
    Test-FreshTimestamp $health.LastReplicaReceive 120 'replica_older_than_120_minutes'
} else {
    $errors.Add('server_role_invalid')
}

$health['YandexDiskRunning'] = $yandexRunning
$health['LegacyYandexDiskRunning'] = $legacyYandexRunning
$health['YandexSyncErrors'] = @($errors)
$health['YandexSchedule'] = if ($isPrimary) {
    'Daily 02:00-05:00 Europe/Moscow'
} else {
    'Daily 03:00-05:00 Europe/Moscow'
}
$health['YandexSyncWindowActive'] = $syncWindowActive
$health['YandexNightlyTaskRunning'] = $nightlyTaskRunning
$health['CloudFolderAvailable'] = $cloudAvailable
$health['YandexRouteInterface'] = if ($null -ne $network) {
    [string]$network.ProbeInterface
} else {
    'Not checked while Yandex.Disk is stopped outside the nightly window'
}
$health['YandexHttpsReachable'] = if ($null -ne $network) { [bool]$network.HttpsReachable } else { $null }
$health['YandexAppBypassConfigured'] = if ($null -ne $network) { [bool]$network.AppBypassConfigured } else { $null }
$health['YandexAppBypassConfirmed'] = if ($null -ne $network) { [bool]$network.AppBypassObserved } else { $null }
$health['YandexBypassEvidenceTimestamp'] = if ($null -ne $network) { $network.EvidenceTimestamp } else { $null }
$health['CloudFreeGB'] = $null
$health['CloudFreePercent'] = $null
$health['SyncVolumeFreeGB'] = $syncVolumeFreeGB
$health['SyncVolumeFreePercent'] = $syncVolumeFreePercent
$health['CloudStatus'] = if (-not $cloudAvailable) {
    'UNAVAILABLE'
} elseif ($yandexRunning) {
    'NIGHTLY_SYNC_ACTIVE'
} else {
    'LOCAL_CACHE_AVAILABLE_SYNC_STOPPED'
}
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
