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
$pendingPromotionPath = 'C:\IZO_ASA\runtime\pending-release-promotion.json'
$architectureContractPath = Join-Path $root 'architecture\contract.json'
$caddyRuntimeScript = Join-Path $root 'tools\caddy-runtime.ps1'
$runtimeListenerScript = Join-Path $root 'tools\check-runtime-listeners.ps1'

function Test-IzoNormalizedPathEquals {
    param([string]$Left, [string]$Right)

    $normalizedLeft = [IO.Path]::GetFullPath($Left)
    $normalizedRight = [IO.Path]::GetFullPath($Right)
    return [string]::Equals($normalizedLeft, $normalizedRight, [StringComparison]::OrdinalIgnoreCase)
}

function Test-IzoNormalizedPathWithin {
    param([string]$Path, [string]$Root)

    $normalizedPath = [IO.Path]::GetFullPath($Path)
    $normalizedRoot = [IO.Path]::GetFullPath($Root)
    if (-not $normalizedRoot.EndsWith([string][IO.Path]::DirectorySeparatorChar)) {
        $normalizedRoot += [IO.Path]::DirectorySeparatorChar
    }
    return $normalizedPath.StartsWith($normalizedRoot, [StringComparison]::OrdinalIgnoreCase)
}

function Convert-IzoRecoveryDatabasePath {
    param([string]$DatabaseUrl)

    if ($DatabaseUrl -notmatch '^sqlite:///') {
        throw 'Stopped-backend recovery supports only the installed SQLite topology.'
    }
    # Keep -replace outside the method call: its comma becomes a second argument in PS 5.1.
    $nativePath = ($DatabaseUrl -replace '^sqlite:///', '') -replace '/', '\'
    return [IO.Path]::GetFullPath($nativePath)
}

if ($PlanOnly) {
    $pathCompatibilityRoot = Join-Path $root '.stopped-backend-recovery-path-probe'
    $pathCompatibilityChild = Join-Path $pathCompatibilityRoot 'manifest.json'
    if (-not (Test-IzoNormalizedPathEquals -Left $root -Right $root) -or
        -not (Test-IzoNormalizedPathWithin -Path $pathCompatibilityChild -Root $pathCompatibilityRoot)) {
        throw 'Stopped-backend recovery normalized-path compatibility probe failed.'
    }
    $databaseCompatibilityUrl = 'sqlite:///' + $pathCompatibilityChild.Replace('\', '/')
    $databaseCompatibilityPath = Convert-IzoRecoveryDatabasePath -DatabaseUrl $databaseCompatibilityUrl
    if (-not (Test-IzoNormalizedPathEquals -Left $databaseCompatibilityPath -Right $pathCompatibilityChild)) {
        throw 'Stopped-backend recovery database URL compatibility probe failed.'
    }
    Write-Host "STOPPED_BACKEND_RECOVERY_PLAN check=$Check root=$root"
    Write-Host 'STOPPED_BACKEND_RECOVERY_PLAN_STEP pathComparison=windows-powershell-5.1-compatible'
    Write-Host 'STOPPED_BACKEND_RECOVERY_PLAN_STEP databaseUrl=windows-powershell-5.1-compatible'
    Write-Host 'STOPPED_BACKEND_RECOVERY_PLAN_STEP state=rolled_back,update-promotion_failed-or-clean-canonical-promotion_pending'
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
    $architectureContractPath,
    $caddyRuntimeScript,
    $runtimeListenerScript
)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Stopped-backend recovery evidence is missing: $path"
    }
}
. (Join-Path $root 'tools\repository-operation-lock.ps1')
. (Join-Path $root 'ops\release\recovery-service-guard.ps1')
$guardHead = ([string](& git.exe -C $root rev-parse HEAD)).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Recovery source commit could not be resolved.' }
$null = Assert-IzoRecoveryMaintenance -RepoRoot $root -ExpectedSha $guardHead `
    -MaintenancePath $maintenanceFlagPath -RequireStopped

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
if (-not (Test-IzoNormalizedPathEquals -Left $registeredExecutable -Right $expectedServiceExecutable)) {
    throw 'IZOBackend is not registered to the installed WinSW executable.'
}
$backendListeners = @(Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue)
if ($backendListeners.Count -ne 0) {
    throw 'Port 8000 must be closed for stopped-backend recovery verification.'
}
$currentHead = ([string](& git.exe -C $root rev-parse HEAD)).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $currentHead -notmatch '^[0-9a-f]{40}$') {
    throw 'Current exact source commit could not be resolved.'
}
$currentOrigin = ([string](& git.exe -C $root remote get-url origin)).Trim()
if ($LASTEXITCODE -ne 0 -or $currentOrigin -notmatch 'spikeal8-maker/IZO_ASA(?:\.git)?$') {
    throw 'Current exact source has an unexpected Git origin.'
}

$promotion = Get-Content -LiteralPath $promotionPath -Raw -Encoding UTF8 | ConvertFrom-Json
$update = Get-Content -LiteralPath $updatePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($promotion.Ok -ne $false -or [string]$promotion.Stage -ne 'rolled_back') {
    throw 'Promotion evidence is not a completed automatic rollback.'
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
if ([string]$promotion.NewSha -notmatch '^[0-9a-f]{40}$') {
    throw 'Failed candidate identity is invalid.'
}
$updateStatus = [string]$update.Status
if ($updateStatus -eq 'PROMOTION_FAILED') {
    if ([string]$update.RemoteSha -ne [string]$promotion.NewSha) {
        throw 'Failed candidate identity is inconsistent.'
    }
} elseif ($updateStatus -eq 'PROMOTION_PENDING') {
    $pendingSha = ([string]$update.RemoteSha).ToLowerInvariant()
    $expectedCandidatePath = "C:\IZO_ASA\releases\$pendingSha"
    if (
        $pendingSha -notmatch '^[0-9a-f]{40}$' -or
        $pendingSha -eq [string]$promotion.NewSha -or
        [string]$update.CiStatus -ne 'success' -or
        -not (Test-IzoNormalizedPathEquals -Left ([string]$update.CandidatePath) -Right $expectedCandidatePath)
    ) {
        throw 'Pending corrective candidate is not bound to a distinct exact SHA and successful CI.'
    }
    & git.exe -C $root merge-base --is-ancestor $pendingSha $currentHead
    if ($LASTEXITCODE -ne 0) {
        throw 'Pending corrective candidate is not the current exact source or its canonical ancestor.'
    }
    if (-not (Test-Path -LiteralPath $pendingPromotionPath -PathType Leaf)) {
        throw 'Pending corrective candidate marker is missing.'
    }
    $pendingPromotion = Get-Content -LiteralPath $pendingPromotionPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (
        [string]$pendingPromotion.NewSha -ne $pendingSha -or
        -not (Test-IzoNormalizedPathEquals -Left ([string]$pendingPromotion.CandidatePath) -Right $expectedCandidatePath)
    ) {
        throw 'Pending corrective candidate marker does not match updater evidence.'
    }
    if (-not (Test-Path -LiteralPath $expectedCandidatePath -PathType Container)) {
        throw 'Pending corrective candidate checkout is missing.'
    }
    $candidateHead = ([string](& git.exe -C $expectedCandidatePath rev-parse HEAD)).Trim().ToLowerInvariant()
    if ($LASTEXITCODE -ne 0 -or $candidateHead -ne $pendingSha) {
        throw 'Pending corrective candidate checkout has an unexpected Git HEAD.'
    }
    $candidateOrigin = ([string](& git.exe -C $expectedCandidatePath remote get-url origin)).Trim()
    if ($LASTEXITCODE -ne 0 -or $candidateOrigin -notmatch 'spikeal8-maker/IZO_ASA(?:\.git)?$') {
        throw 'Pending corrective candidate checkout has an unexpected Git origin.'
    }
    $candidateChanges = @(& git.exe -C $expectedCandidatePath status --porcelain)
    if ($LASTEXITCODE -ne 0 -or $candidateChanges.Count -ne 0) {
        throw 'Pending corrective candidate checkout has tracked or untracked changes.'
    }
} else {
    throw "Updater evidence has unsupported recovery status: $updateStatus"
}
$oldRelease = [IO.Path]::GetFullPath("C:\IZO_ASA\releases\$oldSha")
$expectedPython = [IO.Path]::GetFullPath((Join-Path $oldRelease 'backend\.venv\Scripts\python.exe'))
$expectedWorkingDirectory = [IO.Path]::GetFullPath((Join-Path $oldRelease 'backend'))
if (-not (Test-IzoNormalizedPathEquals -Left ([string]$backendXml.service.executable) -Right $expectedPython) -or
    -not (Test-IzoNormalizedPathEquals -Left ([string]$backendXml.service.workingdirectory) -Right $expectedWorkingDirectory)) {
    throw 'Installed backend XML does not point to the rolled-back immutable release.'
}
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf) -or
    -not (Test-IzoNormalizedPathWithin -Path $manifestPath -Root $oldRelease)) {
    throw 'Rolled-back release manifest is missing or outside the rolled-back release.'
}
$oldManifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$oldManifest.git_sha -ne $oldSha -or $oldManifest.dirty -ne $false) {
    throw 'Rolled-back release manifest identity is invalid.'
}

$databasePath = Convert-IzoRecoveryDatabasePath -DatabaseUrl $databaseUrl
$allowedDatabaseRoots = @('C:\IZO_ASA\', 'F:\IZO_ASA\', 'F:\IZO_ASA_StandbyData\')
if (-not ($allowedDatabaseRoots | Where-Object { $databasePath.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) })) {
    throw 'Installed database path is outside approved production roots.'
}
if (-not (Test-Path -LiteralPath $databasePath -PathType Leaf)) {
    throw 'Installed production database is missing.'
}
$previousDiagnosticPath = [Environment]::GetEnvironmentVariable('IZO_RECOVERY_DB_PATH', 'Process')
$previousDiagnosticRoot = [Environment]::GetEnvironmentVariable('IZO_RECOVERY_REPO_ROOT', 'Process')
try {
    [Environment]::SetEnvironmentVariable('IZO_RECOVERY_DB_PATH', $databasePath, 'Process')
    [Environment]::SetEnvironmentVariable('IZO_RECOVERY_REPO_ROOT', $root, 'Process')
    $databaseProbeCode = @'
import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path

path = os.environ["IZO_RECOVERY_DB_PATH"].replace("\\", "/")
repo_root = Path(os.environ["IZO_RECOVERY_REPO_ROOT"])
migrations_path = repo_root / "backend" / "app" / "database" / "migrations.py"
spec = importlib.util.spec_from_file_location("izo_recovery_migrations", migrations_path)
if spec is None or spec.loader is None:
    raise RuntimeError("migration definitions could not be loaded")
migrations = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = migrations
spec.loader.exec_module(migrations)
definitions = sorted(
    (value.version, value.name, value.checksum)
    for value in vars(migrations).values()
    if isinstance(value, migrations.MigrationDefinition)
)
if len({definition[0] for definition in definitions}) != len(definitions):
    raise RuntimeError("duplicate migration definition version")

connection = sqlite3.connect("file:" + path + "?mode=ro", uri=True)
try:
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    applied = [
        (int(version), str(name), str(checksum))
        for version, name, checksum in connection.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
    ]
    expected = [definition for definition in definitions if definition[0] <= user_version]
    report = {
        "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
        "user_version": user_version,
        "ledger_max": int(applied[-1][0] if applied else 0),
        "definition_max": int(definitions[-1][0] if definitions else 0),
        "ledger_matches_definitions": applied == expected,
    }
finally:
    connection.close()
print(json.dumps(report, separators=(",", ":")))
'@
    $previousNativeErrorPreference = $ErrorActionPreference
    try {
        # PS 5.1 strips embedded quotes from native -c arguments. Stdin preserves source.
        # Capture the complete diagnostic before enforcing the native exit code.
        $ErrorActionPreference = 'Continue'
        $databaseOutput = @($databaseProbeCode | & $PythonPath - 2>&1)
        $databaseExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousNativeErrorPreference
    }
    if ($databaseExitCode -ne 0 -or $databaseOutput.Count -eq 0) {
        throw "Read-only database verification failed: $($databaseOutput -join [Environment]::NewLine)"
    }
    $database = ([string]$databaseOutput[-1]) | ConvertFrom-Json
} finally {
    [Environment]::SetEnvironmentVariable('IZO_RECOVERY_DB_PATH', $previousDiagnosticPath, 'Process')
    [Environment]::SetEnvironmentVariable('IZO_RECOVERY_REPO_ROOT', $previousDiagnosticRoot, 'Process')
}
if (
    [string]$database.quick_check -ne 'ok' -or
    [int]$database.user_version -ne [int]$database.ledger_max -or
    [int]$database.definition_max -lt [int]$database.user_version -or
    $database.ledger_matches_definitions -ne $true
) {
    throw 'Production database integrity or migration ledger verification failed.'
}
$contract = Get-Content -LiteralPath $architectureContractPath -Raw -Encoding UTF8 | ConvertFrom-Json
$currentMin = [int]$contract.release_contract.schema_compatibility.min_version
$currentMax = [int]$contract.release_contract.schema_compatibility.max_version
$oldMax = [int]$oldManifest.schema_compatibility.max_version
if ($currentMin -gt [int]$database.user_version -or $currentMax -lt [int]$database.user_version) {
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
    if ($currentHead -eq [string]$promotion.NewSha) {
        throw 'Current exact source is the already-failed candidate; a corrective commit is required.'
    }
    Write-Host "STOPPED_BACKEND_RECOVERY_PREFLIGHT_OK current=$currentHead previous=$oldSha failed=$($promotion.NewSha) update=$updateStatus schema=$($database.user_version) currentMin=$currentMin currentMax=$currentMax previousMax=$oldMax"
    exit 0
}

$caddyService = Get-CimInstance Win32_Service -Filter "Name='IZOCaddy'" -ErrorAction Stop
. $caddyRuntimeScript
$caddyRuntime = Get-IzoCaddyRuntime -RepoRoot $root -RequireInstalled
$caddyListenerState = Get-IzoFrontendListenerState -Runtime $caddyRuntime -Port 5173
if (
    [string]$caddyService.State -ne 'Running' -or
    [int]$caddyService.ProcessId -le 0 -or
    [string]$caddyListenerState.Kind -ne 'caddy' -or
    [string]$caddyListenerState.Listener.LocalAddress -ne '127.0.0.1' -or
    [int]$caddyListenerState.Process.ParentProcessId -ne [int]$caddyService.ProcessId
) {
    throw 'IZOCaddy WinSW service must own the single pinned Caddy IPv4 loopback listener on port 5173.'
}
if ($Check -eq 'Listeners') {
    $listenerOutput = @(
        & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File $runtimeListenerScript -RepoRoot $root `
            -ContractPath $architectureContractPath -AllowStoppedInstalledBackend 2>&1
    )
    $listenerExitCode = $LASTEXITCODE
    $listenerOutput | ForEach-Object { Write-Host $_ }
    if ($listenerExitCode -ne 0) {
        throw "Global runtime listener validation failed with exit code $listenerExitCode."
    }
    Write-Host "STOPPED_BACKEND_RECOVERY_LISTENERS_OK backend=stopped apiPort=closed caddy=running caddyPid=$($caddyListenerState.Process.ProcessId) servicePid=$($caddyService.ProcessId)"
    exit 0
}

$caddyText = Get-Content -LiteralPath $caddyConfigPath -Raw -Encoding UTF8
$releasePath = [IO.Path]::GetFullPath((Split-Path -Parent $manifestPath))
if ($caddyText -notmatch [regex]::Escape($releasePath)) {
    throw 'Caddy frontend root does not match the rolled-back release manifest.'
}
$hostHeader = @{ Host = 'izo.alikinas.ru' }
$releaseMarker = 'name=' + [char]34 + 'izo-release' + [char]34 + ' content=' + [char]34 + [string]$oldManifest.release_id + [char]34
foreach ($route in @('/', '/chat')) {
    $edge = Get-HttpStatus -Uri "http://127.0.0.1:5173$route" -Headers $hostHeader
    if ($edge.Status -ne 200 -or -not ([string]$edge.Response.Content).Contains($releaseMarker)) {
        throw "Rolled-back static edge route failed: $route"
    }
}
$api = Get-HttpStatus -Uri 'http://127.0.0.1:5173/api/health' -Headers $hostHeader
if ($api.Status -ne 502) {
    throw "Stopped backend must produce an explicit 502 through Caddy; received $($api.Status)."
}
Write-Host "STOPPED_BACKEND_RECOVERY_EDGE_OK release=$($oldManifest.release_id) static=200 api=502"
