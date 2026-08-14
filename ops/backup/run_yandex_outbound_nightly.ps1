[CmdletBinding()]
param(
    [string]$OperationsConfig = 'C:\IZO_ASA\config\backup-operations.json',
    [string]$StatusPath = 'C:\IZO_ASA\health\future-primary-outbound-current.json',
    [ValidateRange(1, 45)]
    [int]$BackupWaitMinutes = 15
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$startedAt = Get-Date
$runtime = Split-Path -Parent $MyInvocation.MyCommand.Path
$networkScript = Join-Path $runtime 'yandex_network.ps1'
$localBackupScript = Join-Path $runtime 'run_local_backup.ps1'
$cloudStageScript = Join-Path $runtime 'stage_cloud_backup.ps1'
$guardScript = Join-Path $runtime 'yandex_daytime_guard.ps1'
$lockPath = Join-Path $runtime 'future-primary-outbound.lock'
$yandexExe = 'C:\Users\admins\AppData\Local\Programs\Yandex\YandexDisk4\YandexDisk4.exe'
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$runName = 'Yandex.Disk.4'
$lock = $null
$utf8NoBom = [Text.UTF8Encoding]::new($false)
$logDirectory = 'C:\IZO_ASA\logs\yandex-outbound'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$log = Join-Path $logDirectory ("yandex-outbound-{0}.log" -f $startedAt.ToString('yyyyMMdd-HHmmss'))

function Write-JsonUtf8NoBom {
    param([object]$Document, [string]$Path)
    [IO.File]::WriteAllText($Path, ($Document | ConvertTo-Json -Depth 8) + "`n", [Text.UTF8Encoding]::new($false))
}

function Write-RunStatus {
    param(
        [string]$Status,
        [string]$Phase,
        [string]$Message,
        [string]$ErrorText = '',
        [string]$ErrorType = '',
        [string]$FullyQualifiedErrorId = '',
        [string]$ScriptStackTrace = '',
        [string]$PositionMessage = '',
        [object]$NetworkState = $null
    )
    $document = [ordered]@{
        Timestamp = (Get-Date).ToString('o')
        StartedAt = $startedAt.ToString('o')
        Status = $Status
        Phase = $Phase
        Message = $Message
        Error = $ErrorText
        ErrorType = $ErrorType
        FullyQualifiedErrorId = $FullyQualifiedErrorId
        ScriptStackTrace = $ScriptStackTrace
        PositionMessage = $PositionMessage
        LogPath = $log
        Schedule = 'Local every 30m; Yandex.Disk upload daily 02:00-05:00 Europe/Moscow'
        YandexDiskRunning = [bool](Get-Process -Name YandexDisk4 -ErrorAction SilentlyContinue)
        YandexNetwork = $NetworkState
    }
    Write-JsonUtf8NoBom -Document $document -Path $StatusPath
}

function Write-Log {
    param([string]$Message)
    $line = '[{0}] {1}' -f (Get-Date).ToString('o'), $Message
    [IO.File]::AppendAllText($log, $line + [Environment]::NewLine, $utf8NoBom)
    Write-Host $line
}

function Read-BackupHealth {
    param([string]$HealthPath)
    if (-not (Test-Path -LiteralPath $HealthPath -PathType Leaf)) { return $null }
    try { return Get-Content -LiteralPath $HealthPath -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { return $null }
}

function Test-FreshVerifiedBackup {
    param([object]$Health, [DateTimeOffset]$NotOlderThan)
    if ($null -eq $Health -or -not $Health.LastVerifiedBackup) { return $false }
    try { $verified = [DateTimeOffset]::Parse([string]$Health.LastVerifiedBackup) }
    catch { return $false }
    return (
        $verified -ge $NotOlderThan -and
        [string]$Health.LatestSnapshotId -match '^\d{8}T\d{6}\.\d{6}Z$' -and
        [string]$Health.ManifestSha256 -match '^[a-fA-F0-9]{64}$'
    )
}

function Invoke-LoggedPowerShell {
    param(
        [Parameter(Mandatory)][string]$Phase,
        [Parameter(Mandatory)][string]$Script,
        [string[]]$Arguments = @()
    )
    $phaseDirectory = Split-Path -Parent $log
    $phaseBase = Join-Path $phaseDirectory ("{0}-{1}" -f ([IO.Path]::GetFileNameWithoutExtension($log)), $Phase)
    $stdoutPath = "$phaseBase.stdout.log"
    $stderrPath = "$phaseBase.stderr.log"
    $argumentList = @(
        '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
        '-File', $Script
    ) + $Arguments
    Write-Log "PHASE_START phase=$Phase"
    $process = Start-Process -FilePath 'powershell.exe' -ArgumentList $argumentList `
        -WindowStyle Hidden -Wait -PassThru `
        -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    foreach ($path in @($stdoutPath, $stderrPath)) {
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            Get-Content -LiteralPath $path -ErrorAction SilentlyContinue |
                ForEach-Object { Write-Log "PHASE_OUTPUT phase=$Phase $_" }
        }
    }
    Write-Log "PHASE_END phase=$Phase exitCode=$($process.ExitCode)"
    return [int]$process.ExitCode
}

try {
    $config = Get-Content -LiteralPath $OperationsConfig -Raw -Encoding UTF8 | ConvertFrom-Json
    $role = Get-Content -LiteralPath $config.role_config -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($role.role -ne 'PRIMARY' -or $role.databaseWriter -ne $true) {
        throw 'Outbound backup is allowed only on PRIMARY with databaseWriter=true.'
    }

    $now = Get-Date
    $windowStart = $now.Date.AddHours(2)
    $windowEnd = $now.Date.AddHours(5)
    if ($now -lt $windowStart -or $now -ge $windowEnd) {
        throw 'Outbound backup started outside the approved 02:00-05:00 Europe/Moscow window.'
    }

    foreach ($required in @($networkScript, $localBackupScript, $cloudStageScript, $guardScript, $yandexExe)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "Required outbound component is unavailable: $required"
        }
    }

    try {
        $lock = [IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None')
    } catch [System.IO.IOException] {
        Write-RunStatus -Status 'SKIPPED_ALREADY_RUNNING' -Phase 'LOCK' `
            -Message 'Another outbound backup instance already owns the lock.' `
            -ErrorText $_.Exception.Message
        Write-Warning 'YANDEX_OUTBOUND_SKIPPED_ALREADY_RUNNING'
        exit 3
    }

    Write-RunStatus -Status 'RUNNING' -Phase 'START' -Message 'Nightly PRIMARY outbound backup started.'
    Remove-ItemProperty -Path $runKey -Name $runName -ErrorAction SilentlyContinue
    if (-not (Get-Process -Name YandexDisk4 -ErrorAction SilentlyContinue)) {
        Start-Process -FilePath $yandexExe -ArgumentList '-autostart' -WindowStyle Hidden | Out-Null
        for ($attempt = 0; $attempt -lt 60; $attempt++) {
            if (Get-Process -Name YandexDisk4 -ErrorAction SilentlyContinue) { break }
            Start-Sleep -Seconds 1
        }
    }
    if (-not (Get-Process -Name YandexDisk4 -ErrorAction SilentlyContinue)) {
        throw 'Yandex.Disk did not start.'
    }
    Remove-ItemProperty -Path $runKey -Name $runName -ErrorAction SilentlyContinue

    . $networkScript
    $network = Get-IzoYandexNetworkState -YandexExecutable $yandexExe
    Write-RunStatus -Status 'RUNNING' -Phase 'NETWORK' -Message 'Yandex network preflight completed.' -NetworkState $network
    if (-not $network.HttpsReachable) {
        throw 'Yandex.Disk HTTPS connectivity check failed.'
    }
    if (-not $network.DirectRouteVerified -and -not $network.AppBypassConfigured) {
        throw 'Yandex.Disk has neither a verified direct route nor the legacy AdGuard application bypass.'
    }
    if ($network.RequiresAppBypassEvidence -and -not $network.AppBypassObserved) {
        Write-Log 'NETWORK_WARNING process-specific bypass was configured but not observed in recent AdGuard logs.'
    }

    $freshThreshold = [DateTimeOffset]::Now.AddMinutes(-45)
    $health = Read-BackupHealth -HealthPath ([string]$config.health_file)
    if (-not (Test-FreshVerifiedBackup -Health $health -NotOlderThan $freshThreshold)) {
        $backupExit = Invoke-LoggedPowerShell -Phase 'local-backup' -Script $localBackupScript `
            -Arguments @('-OperationsConfig', $OperationsConfig, '-MaxAttempts', '1', '-RetryDelaySeconds', '0')
        if ($backupExit -eq 3) {
            Write-Log "BACKUP_WAIT reason=already_running maximumMinutes=$BackupWaitMinutes"
            $deadline = (Get-Date).AddMinutes($BackupWaitMinutes)
            do {
                Start-Sleep -Seconds 5
                $health = Read-BackupHealth -HealthPath ([string]$config.health_file)
                if (Test-FreshVerifiedBackup -Health $health -NotOlderThan $freshThreshold) { break }
            } while ((Get-Date) -lt $deadline)
        } elseif ($backupExit -ne 0) {
            throw "Fresh local backup failed with exit code $backupExit."
        }
    }

    $health = Read-BackupHealth -HealthPath ([string]$config.health_file)
    if (-not (Test-FreshVerifiedBackup -Health $health -NotOlderThan $freshThreshold)) {
        throw 'No fresh verified local backup became available before cloud staging.'
    }
    Write-Log "LOCAL_BACKUP_READY snapshot=$($health.LatestSnapshotId)"

    $stageExit = Invoke-LoggedPowerShell -Phase 'cloud-stage' -Script $cloudStageScript `
        -Arguments @('-OperationsConfig', $OperationsConfig)
    if ($stageExit -ne 0) {
        throw "Cloud stage failed with exit code $stageExit."
    }

    $health = Read-BackupHealth -HealthPath ([string]$config.health_file)
    if ($null -eq $health -or -not $health.LastCloudStage) {
        throw 'Cloud stage returned success without recording LastCloudStage.'
    }
    $cloudTimestamp = [DateTimeOffset]::Parse([string]$health.LastCloudStage)
    if ($cloudTimestamp -lt [DateTimeOffset]::Now.AddMinutes(-30)) {
        throw 'Cloud stage returned success with a stale LastCloudStage.'
    }

    Write-RunStatus -Status 'STAGED_SYNCING' -Phase 'COMPLETE' `
        -Message "Verified snapshot $($health.LatestSnapshotId) was staged; Yandex.Disk remains online until the 05:00 guard." `
        -NetworkState $network
    Write-Log "YANDEX_OUTBOUND_OK snapshot=$($health.LatestSnapshotId)"
    exit 0
} catch {
    $errorRecord = $_
    Write-RunStatus -Status 'ERROR' -Phase 'FAILED' -Message 'Nightly PRIMARY outbound backup failed.' `
        -ErrorText $errorRecord.Exception.Message `
        -ErrorType $errorRecord.Exception.GetType().FullName `
        -FullyQualifiedErrorId ([string]$errorRecord.FullyQualifiedErrorId) `
        -ScriptStackTrace ([string]$errorRecord.ScriptStackTrace) `
        -PositionMessage ([string]$errorRecord.InvocationInfo.PositionMessage)
    if ($log) {
        Write-Log (
            "YANDEX_OUTBOUND_ERROR type={0} id={1} message={2} position={3}" -f
            $errorRecord.Exception.GetType().FullName,
            [string]$errorRecord.FullyQualifiedErrorId,
            $errorRecord.Exception.Message,
            ([string]$errorRecord.InvocationInfo.PositionMessage -replace '[\r\n]+', ' ')
        )
    }
    Write-Error $errorRecord
    exit 1
} finally {
    Remove-ItemProperty -Path $runKey -Name $runName -ErrorAction SilentlyContinue
    if ($null -ne $lock) { $lock.Dispose() }
}
