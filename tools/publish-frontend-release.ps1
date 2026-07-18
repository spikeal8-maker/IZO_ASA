[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$PythonPath = "",
    [string]$VerificationReceiptPath = "",
    [string]$BreakGlassAuthorizationPath = "",
    [switch]$PlanOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path) }
$root = (Resolve-Path -LiteralPath $RepoRoot).Path
$frontend = Join-Path $root "frontend"
$runtime = Join-Path $root ".runtime"
$releases = Join-Path $runtime "releases\frontend"
$activeManifest = Join-Path $runtime "active-frontend.json"
$manifestBuilder = Join-Path $root "tools\build_release_manifest.py"
$receiptTool = Join-Path $root "tools\release_verification_receipt.py"
$caddyHelper = Join-Path $root "tools\caddy-runtime.ps1"
$projectPython = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $caddyHelper -PathType Leaf)) {
    throw "Caddy runtime helper was not found."
}
. $caddyHelper
$caddyRuntime = Get-IzoCaddyRuntime -RepoRoot $root
if ($PythonPath.Trim()) {
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw "Requested release Python was not found." }
    $python = (Resolve-Path -LiteralPath $PythonPath).Path
} else {
    $python = $projectPython
}
if (-not $VerificationReceiptPath.Trim() -and $env:IZO_VERIFICATION_RECEIPT -and $env:IZO_VERIFICATION_RECEIPT.Trim()) {
    $VerificationReceiptPath = $env:IZO_VERIFICATION_RECEIPT.Trim()
}
if (-not $BreakGlassAuthorizationPath.Trim() -and $env:IZO_BREAK_GLASS_AUTHORIZATION -and $env:IZO_BREAK_GLASS_AUTHORIZATION.Trim()) {
    $BreakGlassAuthorizationPath = $env:IZO_BREAK_GLASS_AUTHORIZATION.Trim()
}
if ($VerificationReceiptPath.Trim() -and $BreakGlassAuthorizationPath.Trim()) {
    throw "VerificationReceiptPath and BreakGlassAuthorizationPath are mutually exclusive."
}

function Test-PathWithin {
    param(
        [string]$Path,
        [string]$Parent
    )

    $fullPath = [IO.Path]::GetFullPath($Path)
    $fullParent = [IO.Path]::GetFullPath($Parent).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    return $fullPath.StartsWith($fullParent + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
}

function Get-FileSha256 {
    param([string]$Path)

    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $bytes = $algorithm.ComputeHash($stream)
        return "sha256:" + (($bytes | ForEach-Object { $_.ToString("x2") }) -join "")
    } finally {
        $stream.Dispose()
        $algorithm.Dispose()
    }
}

function Use-BreakGlassAuthorization {
    param(
        [string]$Path,
        [string]$Root,
        [string]$ExpectedSha,
        [string]$ExpectedBranch
    )

    $authorizationRoot = Join-Path $Root ".runtime\audit\release-break-glass\authorizations"
    $resolvedPath = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    if (-not (Test-PathWithin -Path $resolvedPath -Parent $authorizationRoot)) {
        throw "Break-glass authorization must be inside the canonical audit directory."
    }
    $authorization = Get-Content -LiteralPath $resolvedPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (
        $authorization.authorization_version -ne 1 -or
        [string]$authorization.authorization_type -ne "release-break-glass-authorization" -or
        [string]$authorization.status -ne "authorized" -or
        ([string]$authorization.consumed_at).Trim()
    ) {
        throw "Break-glass authorization is invalid or already consumed."
    }
    if (
        [string]$authorization.git_sha -ne $ExpectedSha -or
        [string]$authorization.branch -ne $ExpectedBranch -or
        ([string]$authorization.operator).Trim().Length -lt 3 -or
        ([string]$authorization.reason).Trim().Length -lt 20 -or
        [string]$authorization.acknowledgement -ne "I_ACCEPT_UNVERIFIED_RELEASE_RISK"
    ) {
        throw "Break-glass authorization does not match the release contract."
    }
    try {
        $requestedAt = [DateTimeOffset]::Parse([string]$authorization.requested_at)
        $expiresAt = [DateTimeOffset]::Parse([string]$authorization.expires_at)
    } catch {
        throw "Break-glass authorization timestamps are invalid."
    }
    $now = [DateTimeOffset]::UtcNow
    if ($expiresAt -le $requestedAt -or ($expiresAt - $requestedAt).TotalMinutes -gt 15 -or $now -lt $requestedAt.AddMinutes(-5) -or $now -gt $expiresAt) {
        throw "Break-glass authorization is expired or has an invalid lifetime."
    }
    $authorization.status = "consumed"
    $authorization.consumed_at = $now.ToString("o")
    $temporaryPath = "$resolvedPath.tmp"
    $authorization | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporaryPath -Encoding UTF8
    Move-Item -LiteralPath $temporaryPath -Destination $resolvedPath -Force
    return [pscustomobject]@{
        Path = $resolvedPath
        Id = [string]$authorization.authorization_id
        Operator = [string]$authorization.operator
        Reason = [string]$authorization.reason
        Hash = Get-FileSha256 -Path $resolvedPath
    }
}

function Start-LegacyViteRollback {
    param(
        [string]$VitePath,
        [string]$FrontendDirectory,
        [string]$ReleasePath,
        [int]$Port
    )

    return Start-Process -FilePath "node.exe" -ArgumentList @("`"$VitePath`"", "preview", "--host", "127.0.0.1", "--port", [string]$Port, "--strictPort", "--outDir", "`"$ReleasePath`"") -WorkingDirectory $FrontendDirectory -WindowStyle Hidden -PassThru
}

function Remove-ReleaseCandidate {
    param(
        [string]$Path,
        [string]$ReleaseRoot
    )

    if ($Path -and (Test-PathWithin -Path $Path -Parent $ReleaseRoot)) {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path (Join-Path $root "backend\main.py")) -or -not (Test-Path (Join-Path $root "start-public.bat"))) {
    throw "Refusing release outside the canonical project: $root"
}
$branchOutput = @(& git.exe -C $root branch --show-current)
$branch = if ($branchOutput.Count -gt 0) { ([string]$branchOutput[0]).Trim() } else { "" }
if (-not $branch) { $branch = "detached" }
$fullShaOutput = @(& git.exe -C $root rev-parse HEAD)
if ($LASTEXITCODE -ne 0 -or $fullShaOutput.Count -eq 0) { throw "Unable to resolve the release commit." }
$fullSha = ([string]$fullShaOutput[0]).Trim()
if ($fullSha -notmatch "^[0-9a-f]{40}$") { throw "Release commit must be a full lowercase SHA." }
$sha = $fullSha.Substring(0, 12)
$dirty = @(& git.exe -C $root status --porcelain)
if ($branch -ne "main" -and -not $PlanOnly) { throw "Frontend releases are allowed only from main; current branch: $branch" }
if ($dirty.Count -gt 0 -and -not $PlanOnly) { throw "Refusing release from a dirty worktree." }
$releaseId = "$sha-$(Get-Date -Format 'yyyyMMddHHmmss')"
$releasePath = Join-Path $releases $releaseId

if ($PlanOnly) {
    Write-Host "RELEASE_PLAN root=$root branch=$branch sha=$fullSha python=$python edge=caddy-$($caddyRuntime.Version)"
    if ($BreakGlassAuthorizationPath.Trim()) {
        Write-Host "RELEASE_PLAN_STEP verification=break-glass authorization=$BreakGlassAuthorizationPath audited=true"
    } elseif ($VerificationReceiptPath.Trim()) {
        Write-Host "RELEASE_PLAN_STEP verification=validate-receipt receipt=$VerificationReceiptPath exactSha=true"
    } else {
        Write-Host "RELEASE_PLAN_STEP verification=run-full-and-receipt ttlHours=4 exactSha=true"
    }
    Write-Host "RELEASE_PLAN_STEP build=$releasePath"
    Write-Host "RELEASE_PLAN_STEP manifest=$(Join-Path $releasePath 'release-manifest.json')"
    Write-Host "RELEASE_PLAN_STEP caddy_validate=true smoke_port=$($caddyRuntime.CandidatePort) routes=/,/feed,/gallery,/profile"
    Write-Host "RELEASE_PLAN_STEP activation=graceful-reload-or-one-time-vite-migration port=$($caddyRuntime.ProductionPort)"
    Write-Host "RELEASE_PLAN_STEP atomic_manifest=$activeManifest retain=2 rollback=previous-caddy-root"
    return
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python is missing. Create backend\.venv with Python from .python-version before publishing."
}
if (-not (Test-Path -LiteralPath $manifestBuilder -PathType Leaf)) {
    throw "Release manifest builder was not found."
}
if (-not (Test-Path -LiteralPath $receiptTool -PathType Leaf)) {
    throw "Release verification receipt tool was not found."
}
Assert-IzoCaddyRuntime -Runtime $caddyRuntime

New-Item -ItemType Directory -Force -Path $releases | Out-Null
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    Push-Location $frontend
    try { & npm install; if ($LASTEXITCODE -ne 0) { throw "Frontend dependency install failed." } }
    finally { Pop-Location }
}
$verificationKind = "verified"
$verificationEvidencePath = ""
$verificationEvidenceHash = ""
$verificationMode = ""
if ($BreakGlassAuthorizationPath.Trim()) {
    $authorization = Use-BreakGlassAuthorization `
        -Path $BreakGlassAuthorizationPath `
        -Root $root `
        -ExpectedSha $fullSha `
        -ExpectedBranch $branch
    $verificationKind = "break-glass"
    $verificationEvidencePath = $authorization.Path
    $verificationEvidenceHash = $authorization.Hash
    $verificationMode = "unverified-break-glass"
    Write-Warning "BREAK_GLASS_RELEASE authorization=$($authorization.Id) operator=$($authorization.Operator) reason=$($authorization.Reason)"
} else {
    if (-not $VerificationReceiptPath.Trim()) {
        $receiptDirectory = Join-Path $runtime "verification"
        New-Item -ItemType Directory -Force -Path $receiptDirectory | Out-Null
        $receiptName = "$sha-$(Get-Date -Format 'yyyyMMddHHmmss')-$([guid]::NewGuid().ToString('N')).json"
        $VerificationReceiptPath = Join-Path $receiptDirectory $receiptName
        & powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $root "tools\verify.ps1") -Mode Full -RepoRoot $root -PythonPath $python -ReceiptPath $VerificationReceiptPath
        if ($LASTEXITCODE -ne 0) { throw "Release verification failed; no candidate was built." }
    }
    $resolvedReceipt = (Resolve-Path -LiteralPath $VerificationReceiptPath -ErrorAction Stop).Path
    $receiptValidation = @(& $python $receiptTool validate --root $root --receipt $resolvedReceipt --expected-sha $fullSha 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Release verification receipt validation failed: $($receiptValidation -join [Environment]::NewLine)"
    }
    $receiptValidation | Write-Host
    $receiptPayload = Get-Content -LiteralPath $resolvedReceipt -Raw -Encoding UTF8 | ConvertFrom-Json
    $verificationEvidencePath = $resolvedReceipt
    $verificationEvidenceHash = Get-FileSha256 -Path $resolvedReceipt
    $verificationMode = [string]$receiptPayload.mode
    Write-Host "RELEASE_VERIFICATION_RECEIPT_OK path=$resolvedReceipt sha=$fullSha mode=$verificationMode"
}

New-Item -ItemType Directory -Force -Path $releasePath | Out-Null
try {
    Push-Location $frontend
    try {
        $env:FRONTEND_BUILD_LABEL = $releaseId
        & npm run build -- --outDir $releasePath --emptyOutDir
        if ($LASTEXITCODE -ne 0) { throw "TypeScript or Vite release build failed." }
    } finally { Pop-Location }

    $builtAt = (Get-Date).ToUniversalTime().ToString("o")
    & $python $manifestBuilder --root $root --release-path $releasePath --release-id $releaseId --git-sha $fullSha --built-at $builtAt
    if ($LASTEXITCODE -ne 0) { throw "Immutable release manifest generation failed." }
    $releaseManifestPath = Join-Path $releasePath "release-manifest.json"
    $releaseInfo = [ordered]@{
        release_id = $releaseId
        git_sha = $fullSha
        built_at = $builtAt
        verification_kind = $verificationKind
        verification_mode = $verificationMode
        verification_evidence_sha256 = $verificationEvidenceHash
    }
    $releaseInfo | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $releasePath "release.json") -Encoding utf8
} catch {
    Remove-ReleaseCandidate -Path $releasePath -ReleaseRoot $releases
    throw
}

$vite = Join-Path $frontend "node_modules\vite\bin\vite.js"
$candidateProcess = $null
try {
    if (Get-NetTCPConnection -LocalPort $caddyRuntime.CandidatePort -State Listen -ErrorAction SilentlyContinue) {
        throw "Caddy candidate port is already occupied."
    }
    if (Get-NetTCPConnection -LocalPort ([int]($caddyRuntime.CandidateAdminAddress.Split(":")[-1])) -State Listen -ErrorAction SilentlyContinue) {
        throw "Caddy candidate admin port is already occupied."
    }
    Set-IzoCaddyEnvironment `
        -Runtime $caddyRuntime `
        -ReleasePath $releasePath `
        -ReleaseId $releaseId `
        -Port $caddyRuntime.CandidatePort `
        -AdminAddress $caddyRuntime.CandidateAdminAddress `
        -Scope candidate | Out-Null
    Invoke-IzoCaddyValidate -Runtime $caddyRuntime
    $candidatePidDirectory = Join-Path $runtime "caddy"
    New-Item -ItemType Directory -Force -Path $candidatePidDirectory | Out-Null
    $candidateProcess = Start-IzoCaddyProcess -Runtime $caddyRuntime -PidFile (Join-Path $candidatePidDirectory "candidate.pid")
    if (-not (Test-IzoCaddyReleaseReady -Port $caddyRuntime.CandidatePort -ReleaseId $releaseId -Attempts 60)) {
        throw "Caddy candidate did not become ready."
    }
    Push-Location $frontend
    try {
        $env:IZO_SYNTHETIC_BASE_URL = "http://127.0.0.1:$($caddyRuntime.CandidatePort)"
        $env:FRONTEND_BUILD_LABEL = $releaseId
        & npm run e2e:synthetic
        if ($LASTEXITCODE -ne 0) { throw "Candidate browser smoke failed." }
    } finally { Pop-Location }
} catch {
    Remove-ReleaseCandidate -Path $releasePath -ReleaseRoot $releases
    throw
} finally {
    if ($null -ne $candidateProcess) {
        Stop-IzoCaddyProcess -Runtime $caddyRuntime -AdminAddress $caddyRuntime.CandidateAdminAddress -Process $candidateProcess
        if (-not (Wait-IzoFrontendPortFree -Port $caddyRuntime.CandidatePort)) {
            throw "Caddy candidate port did not become free after smoke."
        }
    }
}

$previousState = $null
$previous = $null
if (Test-Path $activeManifest) {
    $previousState = Get-Content $activeManifest -Raw | ConvertFrom-Json
    $previous = [string]$previousState.active_release
}
$manifest = [ordered]@{
    active_release = $releaseId
    previous_release = $previous
    release_path = $releasePath
    release_manifest = $releaseManifestPath
    git_sha = $fullSha
    verification_kind = $verificationKind
    verification_mode = $verificationMode
    verification_evidence = $verificationEvidencePath
    verification_evidence_sha256 = $verificationEvidenceHash
    activated_at = (Get-Date).ToUniversalTime().ToString("o")
}
$tempManifest = "$activeManifest.tmp"
$manifest | ConvertTo-Json | Set-Content -LiteralPath $tempManifest -Encoding utf8

$productionProcess = $null
$legacyListenerStopped = $false
$caddyConfigurationMayHaveChanged = $false
$activationMode = ""
$listenerStateBefore = $null
$previousPath = if ($null -ne $previousState) { [string]$previousState.release_path } else { "" }
try {
    Set-IzoCaddyEnvironment `
        -Runtime $caddyRuntime `
        -ReleasePath $releasePath `
        -ReleaseId $releaseId `
        -Port $caddyRuntime.ProductionPort `
        -AdminAddress $caddyRuntime.ProductionAdminAddress `
        -Scope production | Out-Null
    Invoke-IzoCaddyValidate -Runtime $caddyRuntime
    $listenerStateBefore = Get-IzoFrontendListenerState -Runtime $caddyRuntime -Port $caddyRuntime.ProductionPort
    if ($listenerStateBefore.Kind -eq "caddy") {
        $activationMode = "caddy-reload"
        $caddyConfigurationMayHaveChanged = $true
        Invoke-IzoCaddyReload -Runtime $caddyRuntime -AdminAddress $caddyRuntime.ProductionAdminAddress
    } elseif ($listenerStateBefore.Kind -eq "legacy-vite") {
        $activationMode = "legacy-vite-to-caddy"
        Stop-Process -Id $listenerStateBefore.Process.ProcessId -Force
        $legacyListenerStopped = $true
        if (-not (Wait-IzoFrontendPortFree -Port $caddyRuntime.ProductionPort)) {
            throw "Legacy Vite listener did not release the production port."
        }
        $productionProcess = Start-IzoCaddyProcess -Runtime $caddyRuntime -PidFile (Join-Path $runtime "caddy\production.pid")
        $caddyConfigurationMayHaveChanged = $true
    } elseif ($listenerStateBefore.Kind -eq "none") {
        $activationMode = "cold-caddy-start"
        $productionProcess = Start-IzoCaddyProcess -Runtime $caddyRuntime -PidFile (Join-Path $runtime "caddy\production.pid")
        $caddyConfigurationMayHaveChanged = $true
    } else {
        throw "Port $($caddyRuntime.ProductionPort) has an untrusted listener owner: kind=$($listenerStateBefore.Kind)"
    }
    if (-not (Test-IzoCaddyReleaseReady -Port $caddyRuntime.ProductionPort -ReleaseId $releaseId -Attempts 60)) {
        throw "Activated Caddy edge did not serve the candidate release on the production port."
    }
    $readyListener = Get-IzoFrontendListenerState -Runtime $caddyRuntime -Port $caddyRuntime.ProductionPort
    if ($readyListener.Kind -ne "caddy") {
        throw "Production listener ownership changed before frontend manifest activation."
    }
    Move-Item -LiteralPath $tempManifest -Destination $activeManifest -Force
} catch {
    $activationFailure = $_.Exception.Message
    Remove-Item -LiteralPath $tempManifest -Force -ErrorAction SilentlyContinue
    $rollbackReady = $false
    $previousReleaseComplete = (
        $previous -and
        $previousPath -and
        (Test-PathWithin -Path $previousPath -Parent $releases) -and
        (Test-Path -LiteralPath (Join-Path $previousPath "index.html") -PathType Leaf)
    )
    if ($previousReleaseComplete) {
        try {
            if ($null -ne $productionProcess) {
                Stop-IzoCaddyProcess -Runtime $caddyRuntime -AdminAddress $caddyRuntime.ProductionAdminAddress -Process $productionProcess
                if (-not (Wait-IzoFrontendPortFree -Port $caddyRuntime.ProductionPort)) {
                    throw "Failed Caddy process did not release the production port."
                }
            }
            if ($legacyListenerStopped) {
                $rollbackProcess = Start-LegacyViteRollback -VitePath $vite -FrontendDirectory $frontend -ReleasePath $previousPath -Port $caddyRuntime.ProductionPort
                $rollbackReady = Test-IzoCaddyReleaseReady -Port $caddyRuntime.ProductionPort -ReleaseId $previous -Attempts 60
                if ($rollbackReady) {
                    Write-Host "RELEASE_ACTIVATION_ROLLBACK_OK active=$previous listener=legacy-vite pid=$($rollbackProcess.Id)"
                }
            } elseif ($caddyConfigurationMayHaveChanged) {
                Set-IzoCaddyEnvironment `
                    -Runtime $caddyRuntime `
                    -ReleasePath $previousPath `
                    -ReleaseId $previous `
                    -Port $caddyRuntime.ProductionPort `
                    -AdminAddress $caddyRuntime.ProductionAdminAddress `
                    -Scope production | Out-Null
                Invoke-IzoCaddyValidate -Runtime $caddyRuntime
                $currentState = Get-IzoFrontendListenerState -Runtime $caddyRuntime -Port $caddyRuntime.ProductionPort
                if ($currentState.Kind -eq "caddy") {
                    Invoke-IzoCaddyReload -Runtime $caddyRuntime -AdminAddress $caddyRuntime.ProductionAdminAddress
                } elseif ($currentState.Kind -eq "none") {
                    $rollbackProcess = Start-IzoCaddyProcess -Runtime $caddyRuntime -PidFile (Join-Path $runtime "caddy\production.pid")
                } else {
                    throw "Rollback port has an untrusted listener owner: kind=$($currentState.Kind)"
                }
                $rollbackReady = Test-IzoCaddyReleaseReady -Port $caddyRuntime.ProductionPort -ReleaseId $previous -Attempts 60
                if ($rollbackReady) {
                    Write-Host "RELEASE_ACTIVATION_ROLLBACK_OK active=$previous listener=caddy"
                }
            } else {
                $rollbackReady = Test-IzoCaddyReleaseReady -Port $caddyRuntime.ProductionPort -ReleaseId $previous -Attempts 2
                if ($rollbackReady) {
                    Write-Host "RELEASE_ACTIVATION_ROLLBACK_OK active=$previous listener=preserved"
                }
            }
        } catch {
            Write-Warning "Previous frontend release could not be restored: $($_.Exception.Message)"
            $rollbackReady = $false
        }
    }
    Remove-ReleaseCandidate -Path $releasePath -ReleaseRoot $releases
    if ($rollbackReady) {
        throw "Frontend activation failed and the previous release was restored: $activationFailure"
    }
    throw "Frontend activation failed and rollback was unavailable or failed: $activationFailure"
}

$keep = @($releaseId, $previous) | Where-Object { $_ } | Select-Object -Unique
try {
    Get-ChildItem -LiteralPath $releases -Directory | Where-Object { $keep -notcontains $_.Name } | ForEach-Object {
        if ($_.FullName.StartsWith($releases, [StringComparison]::OrdinalIgnoreCase)) { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
    }
} catch {
    Write-Warning "Release retention cleanup failed after successful activation: $($_.Exception.Message)"
}
Write-Host "RELEASE_READY id=$releaseId sha=$fullSha path=$releasePath manifest=$releaseManifestPath previous=$previous edge=caddy-$($caddyRuntime.Version) activation=$activationMode"
