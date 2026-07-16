[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidateSet('PRIMARY', 'STANDBY')]
    [string]$Role,
    [Parameter(Mandatory)]
    [string]$YandexRoot,
    [string]$BackupRoot = 'I:\IZO_ASA_Backups',
    [string]$ReplicaCache = 'D:\IZO_ASA_ReplicaCache',
    [string]$RehearsalRoot = 'D:\IZO_ASA_RestoreTest',
    [string]$RepoRoot,
    [string]$Python,
    [string]$DatabasePath,
    [string]$MediaDir,
    [string]$InstallRoot = 'C:\IZO_ASA'
)

$ErrorActionPreference = 'Stop'
if (-not $RepoRoot) { $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path }

function Assert-NtfsLocalPath {
    param([string]$Path, [string]$Name, [switch]$RequireFixed)
    $root = [System.IO.Path]::GetPathRoot([System.IO.Path]::GetFullPath($Path))
    $drive = Get-CimInstance Win32_LogicalDisk -Filter ("DeviceID='{0}'" -f $root.TrimEnd('\'))
    if (-not $drive) { throw "$Name drive is unavailable: $root" }
    if ($drive.FileSystem -ne 'NTFS') { throw "$Name must use NTFS, found $($drive.FileSystem)." }
    if ($RequireFixed -and $drive.DriveType -ne 3) { throw "$Name must use a fixed internal disk." }
    if (Test-Path -LiteralPath $Path) {
        $item = Get-Item -LiteralPath $Path
        if ($item.LinkType -in @('Junction', 'SymbolicLink')) { throw "$Name cannot use a junction or symbolic link." }
    }
    $full = [IO.Path]::GetFullPath($Path)
    if ($full -match '(?i)\\(OneDrive|Dropbox)(\\|$)' -or $full.StartsWith([IO.Path]::GetTempPath(), [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Name cannot be inside OneDrive, Dropbox, or a temporary directory."
    }
}

function Write-JsonUtf8NoBom {
    param([object]$Document, [string]$Path)
    [IO.File]::WriteAllText($Path, ($Document | ConvertTo-Json -Depth 8) + "`n", [Text.UTF8Encoding]::new($false))
}

if (-not $Python) {
    $venvPython = Join-Path $RepoRoot 'backend\.venv\Scripts\python.exe'
    $Python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { (Get-Command python).Source }
}
if (-not $DatabasePath) { $DatabasePath = Join-Path $RepoRoot 'backend\onenode.sqlite3' }
if (-not $MediaDir) { $MediaDir = Join-Path $RepoRoot 'backend\media' }

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "Python not found: $Python" }
Assert-NtfsLocalPath -Path $YandexRoot -Name 'YandexRoot' -RequireFixed
if ($Role -eq 'PRIMARY') {
    if (-not (Test-Path -LiteralPath $DatabasePath -PathType Leaf)) { throw "Live database not found: $DatabasePath" }
    if (-not (Test-Path -LiteralPath $MediaDir -PathType Container)) { throw "Live media not found: $MediaDir" }
    Assert-NtfsLocalPath -Path $BackupRoot -Name 'BackupRoot'
    $backupDrive = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($BackupRoot))
    if ($backupDrive -eq [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($DatabasePath)) -or
        $backupDrive -eq [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($MediaDir))) {
        throw 'BackupRoot must use a different volume from live database and media.'
    }
}
if ([IO.Path]::GetFullPath($YandexRoot).StartsWith([IO.Path]::GetFullPath($RepoRoot), [StringComparison]::OrdinalIgnoreCase)) {
    throw 'YandexRoot must be outside the repository.'
}
if (-not $WhatIfPreference) {
    if (-not (Test-Path -LiteralPath $YandexRoot -PathType Container)) { throw 'YandexRoot must exist and be fully synchronized before installation.' }
    if (-not (Get-Process -Name YandexDisk4 -ErrorAction SilentlyContinue)) { throw 'YandexDisk4.exe must be running before installation.' }
    if (Get-Process -Name YandexDisk2 -ErrorAction SilentlyContinue) { throw 'Legacy YandexDisk2.exe must be stopped or removed before Disk 4 backup automation is installed.' }
    if ((Get-Service cldflt -ErrorAction SilentlyContinue).Status -ne 'Running') { throw 'Windows cldflt service must be running.' }
    $route = Test-NetConnection disk.yandex.ru -Port 443 -InformationLevel Detailed -WarningAction SilentlyContinue
    if (-not $route.TcpTestSucceeded) { throw 'Yandex.Disk HTTPS connectivity check failed.' }
    if ($route.InterfaceAlias -match '(?i)AdGuard.*VPN') { throw 'Yandex.Disk must be excluded from AdGuard VPN before automation is installed.' }
}

$configDir = Join-Path $InstallRoot 'config'
$runtimeDir = Join-Path $InstallRoot 'runtime'
$healthDir = Join-Path $InstallRoot 'health'
$logDir = Join-Path $InstallRoot 'logs'
foreach ($path in @($configDir, $runtimeDir, $healthDir, $logDir)) {
    if ($PSCmdlet.ShouldProcess($path, 'Create backup operations directory')) {
        New-Item -ItemType Directory -Force -Path $path | Out-Null
    }
}

$roleConfig = Join-Path $configDir 'server-role.json'
$backupConfig = Join-Path $configDir 'backup.json'
$operationsConfig = Join-Path $configDir 'backup-operations.json'
$healthFile = Join-Path $healthDir 'backup-current.json'
$roleDocument = [ordered]@{
    role = $Role
    databaseWriter = ($Role -eq 'PRIMARY')
    computerName = $env:COMPUTERNAME
}
$operationsDocument = [ordered]@{
    version = 1
    active_release = [IO.Path]::GetFullPath($RepoRoot)
    python = [IO.Path]::GetFullPath($Python)
    database_url = 'sqlite:///' + ([IO.Path]::GetFullPath($DatabasePath) -replace '\\', '/')
    media_dir = [IO.Path]::GetFullPath($MediaDir)
    backup_config = $backupConfig
    role_config = $roleConfig
    health_file = $healthFile
    log_root = $logDir
    cloud_root = [IO.Path]::GetFullPath($YandexRoot)
    replica_cache = [IO.Path]::GetFullPath($ReplicaCache)
    rehearsal_root = [IO.Path]::GetFullPath($RehearsalRoot)
}

if ($PSCmdlet.ShouldProcess($configDir, 'Write role and path-only backup configuration')) {
    Write-JsonUtf8NoBom $roleDocument $roleConfig
    if ($Role -eq 'PRIMARY') {
        Write-JsonUtf8NoBom ([ordered]@{ version = 1; backup_root = [IO.Path]::GetFullPath($BackupRoot) }) $backupConfig
    }
    Write-JsonUtf8NoBom $operationsDocument $operationsConfig
    if (-not (Test-Path -LiteralPath $healthFile)) {
        $initialHealth = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'backup-current.example.json') -Raw | ConvertFrom-Json
        Write-JsonUtf8NoBom $initialHealth $healthFile
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'run_local_backup.ps1') -Destination $runtimeDir -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'stage_cloud_backup.ps1') -Destination $runtimeDir -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'receive_cloud_backup.ps1') -Destination $runtimeDir -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'check_backup_health.ps1') -Destination $runtimeDir -Force
}

if ($WhatIfPreference) { return }
$principal = New-ScheduledTaskPrincipal -UserId ("$env:USERDOMAIN\$env:USERNAME") -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) -StartWhenAvailable
$powershell = (Get-Command powershell.exe).Source
if ($Role -eq 'PRIMARY') {
    $localAction = New-ScheduledTaskAction -Execute $powershell -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runtimeDir\run_local_backup.ps1`""
    $repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
    $startup = New-ScheduledTaskTrigger -AtStartup
    $startup.Delay = 'PT5M'
    Register-ScheduledTask -TaskName 'IZO_ASA Local Backup 15m' -Action $localAction -Trigger @($repeat, $startup) -Settings $settings -Principal $principal -Force | Out-Null

    $cloudAction = New-ScheduledTaskAction -Execute $powershell -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runtimeDir\stage_cloud_backup.ps1`""
    $hourly = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(3) -RepetitionInterval (New-TimeSpan -Hours 1)
    Register-ScheduledTask -TaskName 'IZO_ASA Cloud Stage Hourly' -Action $cloudAction -Trigger $hourly -Settings $settings -Principal $principal -Force | Out-Null
} else {
    $receiveAction = New-ScheduledTaskAction -Execute $powershell -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runtimeDir\receive_cloud_backup.ps1`""
    $hourly = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(3) -RepetitionInterval (New-TimeSpan -Hours 1)
    Register-ScheduledTask -TaskName 'IZO_ASA Replica Receive Hourly' -Action $receiveAction -Trigger $hourly -Settings $settings -Principal $principal -Force | Out-Null

    $rehearseAction = New-ScheduledTaskAction -Execute $powershell -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runtimeDir\receive_cloud_backup.ps1`" -Rehearse"
    $daily = New-ScheduledTaskTrigger -Daily -At '03:30'
    Register-ScheduledTask -TaskName 'IZO_ASA Replica Rehearsal Daily' -Action $rehearseAction -Trigger $daily -Settings $settings -Principal $principal -Force | Out-Null
}
$healthAction = New-ScheduledTaskAction -Execute $powershell -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runtimeDir\check_backup_health.ps1`""
$healthTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName 'IZO_ASA Backup Health 10m' -Action $healthAction -Trigger $healthTrigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "BACKUP_AUTOMATION_INSTALLED role=$Role computer=$env:COMPUTERNAME"
