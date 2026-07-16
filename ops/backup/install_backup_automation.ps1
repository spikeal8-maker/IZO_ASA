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
                throw 'Yandex Disk 3.x and 4.x sync roots must be different and non-nested.'
            }
        }
    }
    if ((Get-Service cldflt -ErrorAction SilentlyContinue).Status -ne 'Running') { throw 'Windows cldflt service must be running.' }
    $route = Test-NetConnection disk.yandex.ru -Port 443 -InformationLevel Detailed -WarningAction SilentlyContinue
    if (-not $route.TcpTestSucceeded) { throw 'Yandex.Disk HTTPS connectivity check failed.' }
    if ($route.InterfaceAlias -match '(?i)AdGuard.*VPN') {
        Write-Warning 'Yandex.Disk is routed through AdGuard VPN. Automation will be installed, but health remains ATTENTION until split tunneling is configured.'
    }
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
        $initialHealth = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'backup-current.example.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        Write-JsonUtf8NoBom $initialHealth $healthFile
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'run_local_backup.ps1') -Destination $runtimeDir -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'run_local_backup_startup.ps1') -Destination $runtimeDir -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'stage_cloud_backup.ps1') -Destination $runtimeDir -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'receive_cloud_backup.ps1') -Destination $runtimeDir -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'check_backup_health.ps1') -Destination $runtimeDir -Force
}

if ($WhatIfPreference) { return }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdministrator = ([Security.Principal.WindowsPrincipal]$identity).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
$runLevel = if ($isAdministrator) { 'HIGHEST' } else { 'LIMITED' }
$expectedTasks = [System.Collections.Generic.List[string]]::new()

function Register-IzoScheduledTask {
    param(
        [string]$Name,
        [string]$Script,
        [ValidateSet('MINUTE', 'HOURLY', 'DAILY', 'ONLOGON')]
        [string]$Schedule,
        [int]$Modifier = 1,
        [string]$StartTime,
        [string]$Delay
    )
    $action = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script"
    $arguments = @('/Create', '/TN', $Name, '/TR', $action, '/SC', $Schedule, '/RL', $runLevel, '/F')
    if ($Schedule -in @('MINUTE', 'HOURLY')) {
        $arguments += @('/MO', [string]$Modifier)
    }
    if ($StartTime) {
        $arguments += @('/ST', $StartTime)
    }
    if ($Delay) {
        $arguments += @('/DELAY', $Delay)
    }
    & schtasks.exe @arguments | Write-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Scheduled task registration failed: $Name"
    }
    $expectedTasks.Add($Name)
}

if ($Role -eq 'PRIMARY') {
    Register-IzoScheduledTask -Name 'IZO_ASA Local Backup 15m' -Script "$runtimeDir\run_local_backup.ps1" -Schedule MINUTE -Modifier 15
    Register-IzoScheduledTask -Name 'IZO_ASA Cloud Stage Hourly' -Script "$runtimeDir\stage_cloud_backup.ps1" -Schedule HOURLY -Modifier 1
} else {
    Register-IzoScheduledTask -Name 'IZO_ASA Replica Receive Hourly' -Script "$runtimeDir\receive_cloud_backup.ps1" -Schedule HOURLY -Modifier 1
    Register-IzoScheduledTask -Name 'IZO_ASA Replica Rehearsal Daily' -Script "$runtimeDir\receive_cloud_backup.ps1 -Rehearse" -Schedule DAILY -StartTime '03:30'
}
Register-IzoScheduledTask -Name 'IZO_ASA Backup Health 10m' -Script "$runtimeDir\check_backup_health.ps1" -Schedule MINUTE -Modifier 10

$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
if ($Role -eq 'PRIMARY') {
    $startupBackup = 'powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' +
        (Join-Path $runtimeDir 'run_local_backup_startup.ps1') + '"'
    Set-ItemProperty -Path $runKey -Name 'IZO_ASA_BackupStartup' -Value $startupBackup
}

$yandexProcess = Get-Process -Name YandexDisk4 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($yandexProcess -and $yandexProcess.Path) {
    $yandexExe = $yandexProcess.Path
    Set-ItemProperty -Path 'HKCU:\Software\Yandex\Yandex.Disk.4' -Name AutoStart -Value 'true'
    Set-ItemProperty -Path $runKey -Name 'IZO_ASA_YandexDisk4' -Value ('"' + $yandexExe + '"')
}

foreach ($taskName in $expectedTasks) {
    if (-not (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) {
        throw "Scheduled task verification failed: $taskName"
    }
}
$startupMode = if ($Role -eq 'PRIMARY') { 'HKCU_RUN_DELAY_5M' } else { 'NONE' }
Write-Host "BACKUP_AUTOMATION_INSTALLED role=$Role computer=$env:COMPUTERNAME runLevel=$runLevel tasks=$($expectedTasks.Count) startup=$startupMode"
