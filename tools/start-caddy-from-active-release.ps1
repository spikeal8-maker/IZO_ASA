[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [switch]$PlanOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if (-not $RepoRoot.Trim()) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$root = (Resolve-Path -LiteralPath $RepoRoot).Path
. (Join-Path $root "tools\caddy-runtime.ps1")
$runtime = Get-IzoCaddyRuntime -RepoRoot $root
$activeManifestPath = Join-Path $root ".runtime\active-frontend.json"
if (-not (Test-Path -LiteralPath $activeManifestPath -PathType Leaf)) {
    throw "Active frontend manifest was not found."
}
$active = Get-Content -LiteralPath $activeManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$releaseId = [string]$active.active_release
$releasePath = [string]$active.release_path
if (-not $releaseId.Trim() -or -not (Test-Path -LiteralPath (Join-Path $releasePath "index.html") -PathType Leaf)) {
    throw "Active frontend manifest points to an incomplete release."
}

if ($PlanOnly) {
    Write-Host "CADDY_START_PLAN version=$($runtime.Version) release=$releaseId path=$releasePath"
    Write-Host "CADDY_START_PLAN_STEP validate=true listener=127.0.0.1:$($runtime.ProductionPort) admin=$($runtime.ProductionAdminAddress)"
    Write-Host "CADDY_START_PLAN_OK activation=start-or-reload unknownOwner=refuse"
    return
}

Assert-IzoCaddyRuntime -Runtime $runtime
Set-IzoCaddyEnvironment -Runtime $runtime -ReleasePath $releasePath -ReleaseId $releaseId -Port $runtime.ProductionPort -AdminAddress $runtime.ProductionAdminAddress -Scope production | Out-Null
Invoke-IzoCaddyValidate -Runtime $runtime
$listenerState = Get-IzoFrontendListenerState -Runtime $runtime -Port $runtime.ProductionPort
if ($listenerState.Kind -eq "caddy") {
    if (-not (Test-IzoCaddyReleaseReady -Port $runtime.ProductionPort -ReleaseId $releaseId -Attempts 2)) {
        Invoke-IzoCaddyReload -Runtime $runtime -AdminAddress $runtime.ProductionAdminAddress
    }
} elseif ($listenerState.Kind -eq "none") {
    $pidDirectory = Join-Path $root ".runtime\caddy"
    New-Item -ItemType Directory -Force -Path $pidDirectory | Out-Null
    $process = Start-IzoCaddyProcess -Runtime $runtime -PidFile (Join-Path $pidDirectory "production.pid")
    Write-Host "CADDY_PROCESS_STARTED pid=$($process.Id)"
} else {
    throw "Port $($runtime.ProductionPort) is not available to the pinned Caddy runtime: kind=$($listenerState.Kind)"
}
if (-not (Test-IzoCaddyReleaseReady -Port $runtime.ProductionPort -ReleaseId $releaseId -Attempts 60)) {
    throw "Pinned Caddy runtime did not serve the active frontend release."
}
$readyState = Get-IzoFrontendListenerState -Runtime $runtime -Port $runtime.ProductionPort
if ($readyState.Kind -ne "caddy") { throw "Caddy listener ownership changed during startup." }
Write-Host "CADDY_START_OK version=$($runtime.Version) release=$releaseId pid=$($readyState.Process.ProcessId)"
