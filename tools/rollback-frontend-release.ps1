[CmdletBinding()]
param(
    [string]$ReleaseId = "",
    [string]$RepoRoot = "",
    [switch]$PlanOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if (-not $RepoRoot.Trim()) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$root = (Resolve-Path -LiteralPath $RepoRoot).Path
$manifestPath = Join-Path $root ".runtime\active-frontend.json"
if (-not (Test-Path (Join-Path $root "backend\main.py")) -or -not (Test-Path $manifestPath)) {
    throw "Canonical active release manifest was not found."
}
. (Join-Path $root "tools\caddy-runtime.ps1")
$runtime = Get-IzoCaddyRuntime -RepoRoot $root
$manifest = Get-Content $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $ReleaseId.Trim()) { $ReleaseId = [string]$manifest.previous_release }
if (-not $ReleaseId.Trim()) { throw "No previous release is available." }
$releaseRoot = Join-Path $root ".runtime\releases\frontend"
$target = Join-Path $releaseRoot $ReleaseId
if (-not (Test-Path (Join-Path $target "index.html") -PathType Leaf)) { throw "Release is incomplete: $ReleaseId" }
$targetManifest = Join-Path $target "release-manifest.json"
$legacyRelease = -not (Test-Path -LiteralPath $targetManifest -PathType Leaf)
if ($PlanOnly) {
    Write-Host "ROLLBACK_PLAN target=$ReleaseId path=$target edge=caddy-$($runtime.Version) smoke=$($runtime.CandidatePort) activation=graceful-reload requiresBackendMatch=true"
    return
}

Assert-IzoCaddyRuntime -Runtime $runtime
$frontend = Join-Path $root "frontend"
$candidateProcess = $null
try {
    if (Get-NetTCPConnection -LocalPort $runtime.CandidatePort -State Listen -ErrorAction SilentlyContinue) {
        throw "Rollback candidate port is already occupied."
    }
    Set-IzoCaddyEnvironment -Runtime $runtime -ReleasePath $target -ReleaseId $ReleaseId -Port $runtime.CandidatePort -AdminAddress $runtime.CandidateAdminAddress -Scope candidate | Out-Null
    Invoke-IzoCaddyValidate -Runtime $runtime
    $candidatePidDirectory = Join-Path $root ".runtime\caddy"
    New-Item -ItemType Directory -Force -Path $candidatePidDirectory | Out-Null
    $candidateProcess = Start-IzoCaddyProcess -Runtime $runtime -PidFile (Join-Path $candidatePidDirectory "rollback-candidate.pid")
    if (-not (Test-IzoCaddyReleaseReady -Port $runtime.CandidatePort -ReleaseId $ReleaseId -Attempts 60)) {
        throw "Rollback Caddy candidate did not become ready."
    }
    Push-Location $frontend
    try {
        $env:IZO_SYNTHETIC_BASE_URL = "http://127.0.0.1:$($runtime.CandidatePort)"
        $env:FRONTEND_BUILD_LABEL = $ReleaseId
        $env:IZO_ALLOW_LEGACY_RELEASE = if ($legacyRelease) { "1" } else { "0" }
        & npm run e2e:synthetic
        if ($LASTEXITCODE -ne 0) { throw "Rollback browser smoke failed." }
    } finally {
        Pop-Location
    }
} finally {
    if ($null -ne $candidateProcess) {
        Stop-IzoCaddyProcess -Runtime $runtime -AdminAddress $runtime.CandidateAdminAddress -Process $candidateProcess
        if (-not (Wait-IzoFrontendPortFree -Port $runtime.CandidatePort)) {
            throw "Rollback candidate port did not become free."
        }
    }
}

$listenerState = Get-IzoFrontendListenerState -Runtime $runtime -Port $runtime.ProductionPort
if ($listenerState.Kind -ne "caddy") {
    throw "Rollback requires the pinned production Caddy listener; current kind=$($listenerState.Kind)"
}
$backendVersion = Invoke-RestMethod "http://127.0.0.1:8000/api/version" -TimeoutSec 10
if ([string]$backendVersion.release_id -ne $ReleaseId) {
    throw "Frontend rollback target does not match the active backend release. Complete the backend rollback first; REL-002 will make this an atomic full-stack operation."
}
$oldActive = [string]$manifest.active_release
$oldPath = [string]$manifest.release_path
$releaseInfo = Get-Content (Join-Path $target "release.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$releaseManifestValue = if (Test-Path -LiteralPath $targetManifest -PathType Leaf) { $targetManifest } else { $null }

try {
    Set-IzoCaddyEnvironment -Runtime $runtime -ReleasePath $target -ReleaseId $ReleaseId -Port $runtime.ProductionPort -AdminAddress $runtime.ProductionAdminAddress -Scope production | Out-Null
    Invoke-IzoCaddyValidate -Runtime $runtime
    Invoke-IzoCaddyReload -Runtime $runtime -AdminAddress $runtime.ProductionAdminAddress
    if (-not (Test-IzoCaddyReleaseReady -Port $runtime.ProductionPort -ReleaseId $ReleaseId -Attempts 60)) {
        throw "Rolled-back Caddy root did not become ready."
    }
    $next = [ordered]@{
        active_release = $ReleaseId
        previous_release = $oldActive
        release_path = $target
        release_manifest = $releaseManifestValue
        git_sha = [string]$releaseInfo.git_sha
        verification_kind = [string]$releaseInfo.verification_kind
        verification_mode = [string]$releaseInfo.verification_mode
        verification_evidence_sha256 = [string]$releaseInfo.verification_evidence_sha256
        activated_at = (Get-Date).ToUniversalTime().ToString("o")
        rollback = $true
    }
    $temp = "$manifestPath.tmp"
    $next | ConvertTo-Json | Set-Content -LiteralPath $temp -Encoding utf8
    Move-Item -LiteralPath $temp -Destination $manifestPath -Force
} catch {
    $failure = $_.Exception.Message
    Remove-Item -LiteralPath "$manifestPath.tmp" -Force -ErrorAction SilentlyContinue
    $restored = $false
    try {
        if ($oldActive -and $oldPath -and (Test-Path -LiteralPath (Join-Path $oldPath "index.html") -PathType Leaf)) {
            Set-IzoCaddyEnvironment -Runtime $runtime -ReleasePath $oldPath -ReleaseId $oldActive -Port $runtime.ProductionPort -AdminAddress $runtime.ProductionAdminAddress -Scope production | Out-Null
            Invoke-IzoCaddyValidate -Runtime $runtime
            Invoke-IzoCaddyReload -Runtime $runtime -AdminAddress $runtime.ProductionAdminAddress
            $restored = Test-IzoCaddyReleaseReady -Port $runtime.ProductionPort -ReleaseId $oldActive -Attempts 60
        }
    } catch {
        Write-Warning "Rollback reversal failed: $($_.Exception.Message)"
    }
    if ($restored) { throw "Frontend rollback failed and the original Caddy root was restored: $failure" }
    throw "Frontend rollback failed and the original Caddy root could not be restored: $failure"
}

Write-Host "ROLLBACK_OK active=$ReleaseId previous=$oldActive edge=caddy-$($runtime.Version)"
