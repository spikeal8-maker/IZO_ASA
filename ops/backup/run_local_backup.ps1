[CmdletBinding()]
param(
    [string]$OperationsConfig = 'C:\IZO_ASA\config\backup-operations.json'
)

$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath $OperationsConfig -Raw | ConvertFrom-Json
$role = Get-Content -LiteralPath $config.role_config -Raw | ConvertFrom-Json
if ($role.role -ne 'PRIMARY' -or $role.databaseWriter -ne $true) {
    throw 'Local backup is allowed only on PRIMARY with databaseWriter=true.'
}

$runtime = Split-Path -Parent $MyInvocation.MyCommand.Path
$lockPath = Join-Path $runtime 'local-backup.lock'
$logDir = [string]$config.log_root
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("local-backup-{0}.log" -f (Get-Date -Format 'yyyyMMdd'))
$lock = $null

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
    Write-Host 'BACKUP_SKIPPED_ALREADY_RUNNING'
    exit 3
}

try {
    $env:DATABASE_URL = [string]$config.database_url
    $env:MEDIA_DIR = [string]$config.media_dir
    $backupTool = Join-Path ([string]$config.active_release) 'tools\backup_production.py'
    $restoreTool = Join-Path ([string]$config.active_release) 'tools\restore_backup.py'
    $transportTool = Join-Path ([string]$config.active_release) 'tools\backup_transport.py'
    Invoke-CheckedPython -Arguments @($backupTool, '--config', [string]$config.backup_config, '--plan') -Expected 'BACKUP_PLAN_OK'
    Invoke-CheckedPython -Arguments @($backupTool, '--config', [string]$config.backup_config) -Expected 'BACKUP_OK'
    Invoke-CheckedPython -Arguments @($restoreTool, '--config', [string]$config.backup_config, '--verify-only') -Expected 'BACKUP_VERIFY_OK'
    Invoke-CheckedPython -Arguments @(
        $transportTool, '--role-config', [string]$config.role_config,
        '--health', [string]$config.health_file,
        'local-status', '--config', [string]$config.backup_config
    ) -Expected 'LOCAL_BACKUP_STATUS_OK'
    Write-Host 'LOCAL_BACKUP_CYCLE_OK'
    exit 0
} catch {
    $_ | Out-String | Tee-Object -FilePath $log -Append | Write-Error
    exit 2
} finally {
    if ($lock) { $lock.Dispose() }
}
