[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [string]$PythonPath = '',
    [Parameter(Mandatory = $true)]
    [ValidateSet('Backend', 'Listeners', 'Edge')]
    [string]$Check,
    [switch]$PlanOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $RepoRoot.Trim()) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$root = (Resolve-Path -LiteralPath $RepoRoot).Path
$expectedServiceExecutable = 'C:\IZO_ASA\runtime\services\backend\IZOBackend.exe'
$backendXmlPath = 'C:\IZO_ASA\runtime\services\backend\IZOBackend.xml'
$caddyConfigPath = 'C:\IZO_ASA\config\Caddyfile'
$healthCheckPath = 'C:\IZO_ASA\ops\scripts\server-health-check.ps1'
$maintenanceFlagPath = 'C:\IZO_ASA\runtime\project-release-maintenance.flag'
$promotionPath = 'C:\IZO_ASA\health\promotion-current.json'
$updatePath = 'C:\IZO_ASA\health\update-current.json'
$architectureContractPath = Join-Path $root 'architecture\contract.json'

if ($PlanOnly) {
    Write-Host "STOPPED_BACKEND_RECOVERY_PLAN check=$Check root=$root"
    Write-Host 'STOPPED_BACKEND_RECOVERY_PLAN_STEP state=rolled_back,promotion_failed'
    Write-Host 'STOPPED_BACKEND_RECOVERY_PLAN_STEP backend=installed-service-stopped,port-8000-closed'
    Write-Host 'STOPPED_BACKEND_RECOVERY_PLAN_STEP database=read-only-quick-check,schema-supported-by-current-contract'
    Write-Host 'STOPPED_BACKEND_RECOVERY_PLAN_STEP caddy=running,loopback-5173,previous-release-static-edge'
    Write-Host "STOPPED_BACKEND_RECOVERY_PLAN_OK check=$Check"
    return
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Stopped-backend recovery verification requires an elevated Windows Administrator process.'
}

if (-not $PythonPath.Trim()) {
    $PythonPath = Join-Path $root 'backend\.venv\Scripts\python.exe'
}
foreach ($path in @(
    $PythonPath,
    $expectedServiceExecutable,
    $backendXmlPath,
    $caddyConfigPath,
    $healthCheckPath,
    $promotionPath,
    $updatePath,
    $architectureContractPath
)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Stopped-backend recovery evidence is missing: $path"
    }
}
if (Test-Path -LiteralPath $maintenanceFlagPath) {
    throw 'Release maintenance flag exists; another mutable operation may be active.'
}

function Get-ServiceEnvironmentValue {
    param([xml]$Document, [string]$Name)

    $matches = @($Document.service.env | Where-Object { [string]$_.name -eq $Name })
    if ($matches.Count -ne 1 -or -not [string]$matches[0].value) {
        throw "Installed backend XML must declare $Name exactly once."
    }
    return [string]$matches[0].value
}

function Get-HttpStatus {
    param([string]$Uri, [hashtable]$Headers = @{})

    try {
        $response = Invoke-WebRequest -Uri $Uri -Headers $Headers -UseBasicParsing -TimeoutSec 15
        return [pscustomobject]@{ Status = [int]$response.StatusCode; Response = $response }
    } catch {
        if ($_.Exception.Response) {
            return [pscustomobject]@{ Status = [int]$_.Exception.Response.StatusCode; Response = $_.Exception.Response }
        }
        throw
    }
}

$service = Get-Service -Name 'IZOBackend' -ErrorAction Stop
$registered = Get-CimInstance Win32_Service -Filter "Name='IZOBackend'" -ErrorAction Stop
if ([string]$service.Status -ne 'Stopped' -or [string]$registered.State -ne 'Stopped' -or [int]$registered.ProcessId -ne 0) {
    throw 'IZOBackend must be a registered stopped service with no service PID.'
}
$registeredExecutable = ([string]$registered.PathName).Trim().Trim('"')
if (-not [IO.Path]::GetFullPath($registeredExecutable).Equals(
    [IO.Path]::GetFullPath($expectedServiceExecutable),
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw 'IZOBackend is not registered to the installed WinSW executable.'
}
$backendListeners = @(Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue)
if ($backendListeners.Count -ne 0) {
    throw 'Port 8000 must be closed for stopped-backend recovery verification.'
}

$promotion = Get-Content -LiteralPath $promotionPath -Raw -Encoding UTF8 | ConvertFrom-Json
$update = Get-Content -LiteralPath $updatePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($promotion.Ok -ne $false -or [string]$promotion.Stage -ne 'rolled_back') {
    throw 'Promotion evidence is not a completed automatic rollback.'
}
if ([string]$update.Status -ne 'PROMOTION_FAILED') {
    throw 'Updater evidence is not PROMOTION_FAILED.'
}

$backendXml = [xml](Get-Content -LiteralPath $backendXmlPath -Raw -Encoding UTF8)
$oldSha = Get-ServiceEnvironmentValue -Document $backendXml -Name 'GIT_COMMIT'
$databaseUrl = Get-ServiceEnvironmentValue -Document $backendXml -Name 'DATABASE_URL'
$manifestPath = Get-ServiceEnvironmentValue -Document $backendXml -Name 'IZO_RELEASE_MANIFEST'
if ($oldSha -notmatch '^[0-9a-f]{40}$') {
    throw 'Installed backend XML has an invalid GIT_COMMIT.'
}
if ([string]$promotion.PreviousSha -ne $oldSha -or [string]$update.ActiveSha -ne $oldSha) {
    throw 'Rollback status, updater status and installed backend commit do not agree.'
}
if ([string]$promotion.NewSha -notmatch '^[0-9a-f]{40}$' -or [string]$update.RemoteSha -ne [string]$promotion.NewSha) {
    throw 'Failed candidate identity is inconsistent.'
}
$oldRelease = [IO.Path]::GetFullPath("C:\IZO_ASA\releases\$oldSha")
$expectedPython = [IO.Path]::GetFullPath((Join-Path $oldRelease 'backend\.venv\Scripts\python.exe'))
$expectedWorkingDirectory = [IO.Path]::GetFullPath((Join-Path $oldRelease 'backend'))
if (-not [IO.Path]::GetFullPath([string]$backendXml.service.executable).Equals($expectedPython, [StringComparison]::OrdinalIgnoreCase) -or
    -not [IO.Path]::GetFullPath([string]$backendXml.service.workingdirectory).Equals($expectedWorkingDirectory, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Installed backend XML does not point to the rolled-back immutable release.'
}
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf) -or
    -not [IO.Path]::GetFullPath($manifestPath).StartsWith($oldRelease + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Rolled-back release manifest is missing or outside the rolled-back release.'
}
$oldManifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$oldManifest.git_sha -ne $oldSha -or $oldManifest.dirty -ne $false) {
    throw 'Rolled-back release manifest identity is invalid.'
}

if ($databaseUrl -notmatch '^sqlite:///') {
    throw 'Stopped-backend recovery supports only the installed SQLite topology.'
}
$databasePath = [IO.Path]::GetFullPath(($databaseUrl -replace '^sqlite:///', '') -replace '/', '\')
$allowedDatabaseRoots = @('C:\IZO_ASA\', 'F:\IZO_ASA\', 'F:\IZO_ASA_StandbyData\')
if (-not ($allowedDatabaseRoots | Where-Object { $databasePath.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) })) {
    throw 'Installed database path is outside approved production roots.'
}
if (-not (Test-Path -LiteralPath $databasePath -PathType Leaf)) {
    throw 'Installed production database is missing.'
}
$previousDiagnosticPath = [Environment]::GetEnvironmentVariable('IZO_RECOVERY_DB_PATH', 'Process')
try {
    [Environment]::SetEnvironmentVariable('IZO_RECOVERY_DB_PATH', $databasePath, 'Process')
    $databaseOutput = @(& $PythonPath -c @'
import json
import os
import sqlite3

path = os.environ["IZO_RECOVERY_DB_PATH"].replace("\\", "/")
connection = sqlite3.connect("file:" + path + "?mode=ro", uri=True)
try:
    report = {
        "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
        "user_version": int(connection.execute("PRAGMA user_version").fetchone()[0]),
        "ledger_max": int(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0),
    }
finally:
    connection.close()
print(json.dumps(report, separators=(",", ":")))
'@ 2>&1)
    if ($LASTEXITCODE -ne 0 -or $databaseOutput.Count -eq 0) {
        throw "Read-only database verification failed: $($databaseOutput -join [Environment]::NewLine)"
    }
    $database = ([string]$databaseOutput[-1]) | ConvertFrom-Json
} finally {
    [Environment]::SetEnvironmentVariable('IZO_RECOVERY_DB_PATH', $previousDiagnosticPath, 'Process')
}
if ([string]$database.quick_check -ne 'ok' -or [int]$database.user_version -ne [int]$database.ledger_max) {
    throw 'Production database integrity or migration ledger verification failed.'
}
$contract = Get-Content -LiteralPath $architectureContractPath -Raw -Encoding UTF8 | ConvertFrom-Json
$currentMax = [int]$contract.release_contract.schema_compatibility.max_version
$oldMax = [int]$oldManifest.schema_compatibility.max_version
if ($currentMax -lt [int]$database.user_version) {
    throw 'Current exact source does not support the live database schema.'
}
if ($oldMax -ge [int]$database.user_version) {
    throw 'Rolled-back release claims to support the live schema; stopped-backend recovery is not justified.'
}
$healthText = Get-Content -LiteralPath $healthCheckPath -Raw -Encoding UTF8
if ($healthText -notmatch [regex]::Escape($maintenanceFlagPath)) {
    throw 'Installed health check does not honor the release maintenance flag.'
}

if ($Check -eq 'Backend') {
    $head = ([string](@(& git.exe -C $root rev-parse HEAD)[0])).Trim()
    if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
        throw 'Current exact source commit could not be resolved.'
    }
    Write-Host "STOPPED_BACKEND_RECOVERY_PREFLIGHT_OK current=$head previous=$oldSha schema=$($database.user_version) currentMax=$currentMax previousMax=$oldMax"
    exit 0
}

$caddyService = Get-Service -Name 'IZOCaddy' -ErrorAction Stop
$caddyListeners = @(Get-NetTCPConnection -State Listen -LocalPort 5173 -ErrorAction SilentlyContinue)
if ([string]$caddyService.Status -ne 'Running' -or $caddyListeners.Count -ne 1 -or [string]$caddyListeners[0].LocalAddress -ne '127.0.0.1') {
    throw 'IZOCaddy must own exactly one IPv4 loopback listener on port 5173.'
}
if ($Check -eq 'Listeners') {
    Write-Host "STOPPED_BACKEND_RECOVERY_LISTENERS_OK backend=stopped apiPort=closed caddy=running caddyPid=$($caddyListeners[0].OwningProcess)"
    exit 0
}

$caddyText = Get-Content -LiteralPath $caddyConfigPath -Raw -Encoding UTF8
$releasePath = [IO.Path]::GetFullPath((Split-Path -Parent $manifestPath))
if ($caddyText -notmatch [regex]::Escape($releasePath)) {
    throw 'Caddy frontend root does not match the rolled-back release manifest.'
}
$hostHeader = @{ Host = 'izo.alikinas.ru' }
foreach ($route in @('/', '/feed', '/gallery')) {
    $edge = Get-HttpStatus -Uri "http://127.0.0.1:5173$route" -Headers $hostHeader
    if ($edge.Status -ne 200 -or [string]$edge.Response.Headers['X-IZO-Release'] -ne [string]$oldManifest.release_id) {
        throw "Rolled-back static edge route failed: $route"
    }
}
$api = Get-HttpStatus -Uri 'http://127.0.0.1:5173/api/health' -Headers $hostHeader
if ($api.Status -ne 502) {
    throw "Stopped backend must produce an explicit 502 through Caddy; received $($api.Status)."
}
Write-Host "STOPPED_BACKEND_RECOVERY_EDGE_OK release=$($oldManifest.release_id) static=200 api=502"
