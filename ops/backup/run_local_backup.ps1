[CmdletBinding()]
param(
    [string]$OperationsConfig = 'C:\IZO_ASA\config\backup-operations.json',
    [ValidateRange(1, 4)]
    [int]$MaxAttempts = 4,
    [ValidateRange(0, 3600)]
    [int]$RetryDelaySeconds = 300
)

$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath $OperationsConfig -Raw -Encoding UTF8 | ConvertFrom-Json
$role = Get-Content -LiteralPath $config.role_config -Raw -Encoding UTF8 | ConvertFrom-Json
if ($role.role -ne 'PRIMARY' -or $role.databaseWriter -ne $true) {
    throw 'Local backup is allowed only on PRIMARY with databaseWriter=true.'
}

$runtime = Split-Path -Parent $MyInvocation.MyCommand.Path
$lockPath = Join-Path $runtime 'local-backup.lock'
$logDir = [string]$config.log_root
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("local-backup-{0}.log" -f (Get-Date -Format 'yyyyMMdd'))
$taskName = 'IZO_ASA Local Backup 30m'
$taskStatusPath = Join-Path (Split-Path -Parent ([string]$config.health_file)) 'local-backup-task-current.json'
$lock = $null

function Write-TaskStatus {
    param(
        [bool]$Ok,
        [string]$State,
        [int]$ExitCode,
        [string]$Message
    )
    try {
        $taskInfo = $null
        try { $taskInfo = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction Stop } catch {}
        $backupHealth = $null
        try {
            $backupHealth = Get-Content -LiteralPath ([string]$config.health_file) -Raw -Encoding UTF8 |
                ConvertFrom-Json
        } catch {}
        $document = [ordered]@{
            Timestamp = (Get-Date).ToString('o')
            Ok = $Ok
            TaskName = $taskName
            State = $State
            ExitCode = $ExitCode
            Message = $Message
            NextRunTime = if ($null -ne $taskInfo) { $taskInfo.NextRunTime.ToString('o') } else { $null }
            LastVerifiedBackup = if ($null -ne $backupHealth) { $backupHealth.LastVerifiedBackup } else { $null }
            LatestSnapshotId = if ($null -ne $backupHealth) { $backupHealth.LatestSnapshotId } else { $null }
            ManifestSha256 = if ($null -ne $backupHealth) { $backupHealth.ManifestSha256 } else { $null }
        }
        $temporary = "$taskStatusPath.tmp"
        [IO.File]::WriteAllText(
            $temporary,
            ($document | ConvertTo-Json -Depth 6) + "`n",
            [Text.UTF8Encoding]::new($false)
        )
        Move-Item -LiteralPath $temporary -Destination $taskStatusPath -Force
    } catch {
        Write-Warning "LOCAL_BACKUP_TASK_STATUS_WRITE_FAILED error=$($_.Exception.Message)"
    }
}

function Invoke-CheckedPython {
    param([string[]]$Arguments, [string]$Expected)
    $output = & $config.python @Arguments 2>&1 | Out-String
    $output.TrimEnd() | Tee-Object -FilePath $log -Append | Write-Host
    if ($LASTEXITCODE -ne 0 -or $output -notmatch [regex]::Escape($Expected)) {
        throw "Command failed or did not emit $Expected"
    }
}

try {
    New-Item -ItemType Directory -Force -Path $runtime | Out-Null
    $lock = [System.IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None')
} catch [System.IO.IOException] {
    Write-TaskStatus -Ok $false -State 'SKIPPED_ALREADY_RUNNING' -ExitCode 3 `
        -Message 'Another local backup instance already owns the lock.'
    Write-Host 'BACKUP_SKIPPED_ALREADY_RUNNING'
    exit 3
}

try {
    Write-TaskStatus -Ok $false -State 'RUNNING' -ExitCode -1 `
        -Message 'The scheduled local backup cycle is running.'
    $env:DATABASE_URL = [string]$config.database_url
    $env:MEDIA_DIR = [string]$config.media_dir
    $backupTool = Join-Path ([string]$config.active_release) 'tools\backup_production.py'
    $transportTool = Join-Path ([string]$config.active_release) 'tools\backup_transport.py'
    $retentionTool = Join-Path ([string]$config.active_release) 'tools\prune_backup_snapshots.py'
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            Write-Host "LOCAL_BACKUP_ATTEMPT attempt=$attempt max=$MaxAttempts"
            Invoke-CheckedPython -Arguments @($backupTool, '--config', [string]$config.backup_config, '--plan') -Expected 'BACKUP_PLAN_OK'
            Invoke-CheckedPython -Arguments @($backupTool, '--config', [string]$config.backup_config) -Expected 'BACKUP_OK'
            Invoke-CheckedPython -Arguments @(
                $transportTool, '--role-config', [string]$config.role_config,
                '--health', [string]$config.health_file,
                'local-status', '--config', [string]$config.backup_config
            ) -Expected 'LOCAL_BACKUP_STATUS_OK'
            $retentionReport = Join-Path $logDir 'retention-local-latest.json'
            $retentionArguments = @(
                $retentionTool, '--scope', 'local', '--config', [string]$config.backup_config,
                '--report', $retentionReport, '--apply'
            )
            $retentionOutput = & $config.python @retentionArguments 2>&1 | Out-String
            $retentionOutput.TrimEnd() | Tee-Object -FilePath $log -Append | Write-Host
            if ($LASTEXITCODE -ne 0 -or $retentionOutput -notmatch 'BACKUP_RETENTION_OK') {
                Write-TaskStatus -Ok $false -State 'ATTENTION' -ExitCode 4 `
                    -Message 'The snapshot is verified, but local retention failed.'
                Write-Warning 'LOCAL_BACKUP_RETENTION_FAILED; the verified snapshot remains available and backup retries are suppressed.'
                exit 4
            }
            Write-TaskStatus -Ok $true -State 'READY' -ExitCode 0 `
                -Message 'The scheduled local backup cycle completed and the snapshot is verified.'
            Write-Host "LOCAL_BACKUP_CYCLE_OK attempt=$attempt"
            exit 0
        } catch {
            $_ | Out-String | Tee-Object -FilePath $log -Append | Write-Warning
            if ($attempt -ge $MaxAttempts) {
                Write-TaskStatus -Ok $false -State 'ERROR' -ExitCode 2 `
                    -Message "The local backup cycle failed after $MaxAttempts attempts."
                Write-Warning "LOCAL_BACKUP_CYCLE_FAILED attempts=$MaxAttempts"
                exit 2
            }
            Write-Warning "LOCAL_BACKUP_RETRY_WAIT seconds=$RetryDelaySeconds next_attempt=$($attempt + 1)"
            Start-Sleep -Seconds $RetryDelaySeconds
        }
    }
} finally {
    if ($lock) { $lock.Dispose() }
}
