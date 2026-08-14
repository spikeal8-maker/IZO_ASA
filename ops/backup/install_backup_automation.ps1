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
    $networkScript = Join-Path $PSScriptRoot 'yandex_network.ps1'
    if (-not (Test-Path -LiteralPath $networkScript -PathType Leaf)) {
        throw "Yandex network verifier is unavailable: $networkScript"
    }
    . $networkScript
    $network = Get-IzoYandexNetworkState
    if (-not $network.HttpsReachable) { throw 'Yandex.Disk HTTPS connectivity check failed.' }
    if (-not $network.DirectRouteVerified -and -not $network.AppBypassConfigured) {
        throw 'Yandex.Disk has neither a verified direct route nor the legacy AdGuard application bypass.'
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
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'yandex_network.ps1') -Destination $runtimeDir -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'run_yandex_outbound_nightly.ps1') -Destination $runtimeDir -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'yandex_daytime_guard.ps1') -Destination $runtimeDir -Force
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
        [string]$ScriptArguments,
        [ValidateSet('MINUTE', 'HOURLY', 'DAILY')]
        [string]$Schedule,
        [int]$Modifier = 1,
        [string]$StartTime,
        [switch]$StartWhenAvailable,
        [ValidateSet('CURRENT', 'SYSTEM')]
        [string]$Principal = 'CURRENT'
    )
    $action = 'powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $Script + '"'
    if ($ScriptArguments) {
        $action += ' ' + $ScriptArguments
    }
    $arguments = @('/Create', '/TN', $Name, '/TR', $action, '/SC', $Schedule, '/RL', $runLevel, '/F')
    if ($Schedule -in @('MINUTE', 'HOURLY')) {
        $arguments += @('/MO', [string]$Modifier)
    }
    if ($StartTime) {
        $arguments += @('/ST', $StartTime)
    }
    if ($Principal -eq 'SYSTEM') {
        $arguments += @('/RU', 'SYSTEM')
    }
    & schtasks.exe @arguments | Write-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Scheduled task registration failed: $Name"
    }
    $settingsArguments = @{
        Hidden = $true
        MultipleInstances = 'IgnoreNew'
    }
    if ($StartWhenAvailable) {
        $settingsArguments['StartWhenAvailable'] = $true
    }
    Set-ScheduledTask -TaskName $Name -Settings (New-ScheduledTaskSettingsSet @settingsArguments) | Out-Null
    $expectedTasks.Add($Name)
}

$obsoleteTasks = [System.Collections.Generic.List[string]]::new()
$disabledTasks = [System.Collections.Generic.List[string]]::new()
if ($Role -eq 'PRIMARY') {
    Register-IzoScheduledTask -Name 'IZO_ASA Local Backup 30m' `
        -Script "$runtimeDir\run_local_backup.ps1" -Schedule MINUTE -Modifier 30 `
        -StartTime '00:00' -StartWhenAvailable -Principal SYSTEM

    $interactiveUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $interactivePrincipal = New-ScheduledTaskPrincipal `
        -UserId $interactiveUser -LogonType Interactive -RunLevel Highest
    $interactiveSettings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Hours 4)

    $outboundAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument (
        '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' +
        (Join-Path $runtimeDir 'run_yandex_outbound_nightly.ps1') + '"'
    )
    $outboundTrigger = New-ScheduledTaskTrigger -Daily -At '02:00'
    Register-ScheduledTask -TaskName 'IZO_ASA Yandex Outbound Nightly' `
        -Action $outboundAction -Trigger $outboundTrigger `
        -Principal $interactivePrincipal -Settings $interactiveSettings -Force | Out-Null
    $expectedTasks.Add('IZO_ASA Yandex Outbound Nightly')

    $guardAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument (
        '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' +
        (Join-Path $runtimeDir 'yandex_daytime_guard.ps1') + '"'
    )
    $guardTriggers = @(
        (New-ScheduledTaskTrigger -Daily -At '05:00'),
        (New-ScheduledTaskTrigger -AtLogOn -User $interactiveUser)
    )
    Register-ScheduledTask -TaskName 'IZO_ASA Yandex Daytime Guard' `
        -Action $guardAction -Trigger $guardTriggers `
        -Principal $interactivePrincipal -Settings $interactiveSettings -Force | Out-Null
    $expectedTasks.Add('IZO_ASA Yandex Daytime Guard')

    $obsoleteTasks.Add('IZO_ASA Local Backup 15m')
    $obsoleteTasks.Add('IZO_ASA Local Backup Hourly')
    $obsoleteTasks.Add('IZO_ASA Cloud Stage Hourly')
    $obsoleteTasks.Add('IZO_ASA Cloud Stage Daily 01h')
    $disabledTasks.Add('IZO_ASA Replica Receive Hourly')
    $disabledTasks.Add('IZO_ASA Replica Rehearsal Daily')
    $disabledTasks.Add('IZO_ASA Cloud Backup Stage')
} else {
    Register-IzoScheduledTask -Name 'IZO_ASA Replica Receive Hourly' -Script "$runtimeDir\receive_cloud_backup.ps1" -Schedule HOURLY -Modifier 1
    Register-IzoScheduledTask -Name 'IZO_ASA Replica Rehearsal Daily' -Script "$runtimeDir\receive_cloud_backup.ps1" -ScriptArguments '-Rehearse' -Schedule DAILY -StartTime '03:30' -StartWhenAvailable
}
Register-IzoScheduledTask -Name 'IZO_ASA Backup Health 10m' `
    -Script "$runtimeDir\check_backup_health.ps1" -Schedule MINUTE -Modifier 10 `
    -StartWhenAvailable -Principal SYSTEM

$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
if ($Role -eq 'PRIMARY') {
    $startupBackup = 'powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' +
        (Join-Path $runtimeDir 'run_local_backup_startup.ps1') + '"'
    Set-ItemProperty -Path $runKey -Name 'IZO_ASA_BackupStartup' -Value $startupBackup
}

Remove-ItemProperty -Path $runKey -Name 'IZO_ASA_YandexDisk4' -ErrorAction SilentlyContinue

foreach ($taskName in $expectedTasks) {
    if (-not (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) {
        throw "Scheduled task verification failed: $taskName"
    }
}
foreach ($taskName in $obsoleteTasks) {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        & schtasks.exe /Delete /TN $taskName /F | Write-Host
        if ($LASTEXITCODE -ne 0) {
            throw "Obsolete scheduled task removal failed: $taskName"
        }
    }
}
foreach ($taskName in $disabledTasks) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task -and $task.State -ne 'Disabled') {
        Disable-ScheduledTask -TaskName $taskName | Out-Null
    }
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task -and $task.State -ne 'Disabled') {
        throw "Legacy STANDBY task was not disabled on PRIMARY: $taskName"
    }
}
$startupMode = if ($Role -eq 'PRIMARY') { 'HKCU_RUN_DELAY_5M' } else { 'NONE' }
Write-Host "BACKUP_AUTOMATION_INSTALLED role=$Role computer=$env:COMPUTERNAME runLevel=$runLevel tasks=$($expectedTasks.Count) startup=$startupMode"
