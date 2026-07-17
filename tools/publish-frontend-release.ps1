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
$projectPython = Join-Path $root "backend\.venv\Scripts\python.exe"
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

    return "sha256:" + (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
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

function Start-FrontendPreview {
    param(
        [string]$VitePath,
        [string]$FrontendDirectory,
        [string]$ReleasePath,
        [int]$Port
    )

    return Start-Process -FilePath "node.exe" -ArgumentList @("`"$VitePath`"", "preview", "--host", "127.0.0.1", "--port", [string]$Port, "--strictPort", "--outDir", "`"$ReleasePath`"") -WorkingDirectory $FrontendDirectory -WindowStyle Hidden -PassThru
}

function Test-FrontendReleaseReady {
    param(
        [int]$Port,
        [string]$ReleaseId,
        [int]$Attempts
    )

    $marker = 'name=' + [char]34 + 'izo-release' + [char]34 + ' content=' + [char]34 + $ReleaseId + [char]34
    for ($attempt = 0; $attempt -lt $Attempts; $attempt++) {
        try {
            $response = Invoke-WebRequest "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200 -and $response.Content.Contains($marker)) {
                return $true
            }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Wait-FrontendPortFree {
    param(
        [int]$Port,
        [int]$Attempts = 60
    )

    for ($attempt = 0; $attempt -lt $Attempts; $attempt++) {
        if (-not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
            return $true
        }
        Start-Sleep -Milliseconds 250
    }
    return $false
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
    Write-Host "RELEASE_PLAN root=$root branch=$branch sha=$fullSha python=$python"
    if ($BreakGlassAuthorizationPath.Trim()) {
        Write-Host "RELEASE_PLAN_STEP verification=break-glass authorization=$BreakGlassAuthorizationPath audited=true"
    } elseif ($VerificationReceiptPath.Trim()) {
        Write-Host "RELEASE_PLAN_STEP verification=validate-receipt receipt=$VerificationReceiptPath exactSha=true"
    } else {
        Write-Host "RELEASE_PLAN_STEP verification=run-full-and-receipt ttlHours=4 exactSha=true"
    }
    Write-Host "RELEASE_PLAN_STEP build=$releasePath"
    Write-Host "RELEASE_PLAN_STEP manifest=$(Join-Path $releasePath 'release-manifest.json')"
    Write-Host "RELEASE_PLAN_STEP smoke_port=5197 routes=/,/feed,/gallery,/profile"
    Write-Host "RELEASE_PLAN_STEP atomic_manifest=$activeManifest retain=2"
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
$preview = Start-FrontendPreview -VitePath $vite -FrontendDirectory $frontend -ReleasePath $releasePath -Port 5197
try {
    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        try { if ((Invoke-WebRequest "http://127.0.0.1:5197/" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { $ready = $true; break } } catch {}
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw "Candidate preview did not become ready." }
    Push-Location $frontend
    try {
        $env:IZO_SYNTHETIC_BASE_URL = "http://127.0.0.1:5197"
        $env:FRONTEND_BUILD_LABEL = $releaseId
        & npm run e2e:synthetic
        if ($LASTEXITCODE -ne 0) { throw "Candidate browser smoke failed." }
    } finally { Pop-Location }
} catch {
    Remove-ReleaseCandidate -Path $releasePath -ReleaseRoot $releases
    throw
} finally {
    Stop-Process -Id $preview.Id -Force -ErrorAction SilentlyContinue
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
$previousListenerStopped = $false
try {
    $listeners = @(Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue)
    $listenerPids = @($listeners.OwningProcess | Select-Object -Unique)
    if ($listenerPids.Count -gt 1) {
        throw "Port 5173 has multiple listener owners; refusing activation."
    }
    if ($listenerPids.Count -eq 1) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listenerPids[0])"
        if ($process.CommandLine -notmatch "vite.+preview" -or $process.CommandLine -notlike "*$root*") {
            throw "Port 5173 is not owned by the canonical Vite preview; refusing to stop it."
        }
        Stop-Process -Id $listenerPids[0] -Force
        $previousListenerStopped = $true
        if (-not (Wait-FrontendPortFree -Port 5173)) {
            throw "Previous frontend listener did not release port 5173."
        }
    }
    $productionProcess = Start-FrontendPreview -VitePath $vite -FrontendDirectory $frontend -ReleasePath $releasePath -Port 5173
    if (-not (Test-FrontendReleaseReady -Port 5173 -ReleaseId $releaseId -Attempts 60)) {
        throw "Activated frontend preview did not become ready on port 5173."
    }
    Move-Item -LiteralPath $tempManifest -Destination $activeManifest -Force
} catch {
    $activationFailure = $_.Exception.Message
    Remove-Item -LiteralPath $tempManifest -Force -ErrorAction SilentlyContinue
    if ($null -ne $productionProcess -and -not $productionProcess.HasExited) {
        Stop-Process -Id $productionProcess.Id -Force -ErrorAction SilentlyContinue
    }
    [void](Wait-FrontendPortFree -Port 5173)
    $rollbackReady = $false
    if ($null -ne $previousState -and $previous) {
        $previousPath = [string]$previousState.release_path
        if (-not $previousListenerStopped) {
            $rollbackReady = Test-FrontendReleaseReady -Port 5173 -ReleaseId $previous -Attempts 2
            if ($rollbackReady) {
                Write-Host "RELEASE_ACTIVATION_ROLLBACK_OK active=$previous listener=preserved"
            }
        }
        if (-not $rollbackReady -and (
            $previousPath -and
            (Test-PathWithin -Path $previousPath -Parent $releases) -and
            (Test-Path -LiteralPath (Join-Path $previousPath "index.html") -PathType Leaf)
        )) {
            try {
                $rollbackProcess = Start-FrontendPreview -VitePath $vite -FrontendDirectory $frontend -ReleasePath $previousPath -Port 5173
                $rollbackReady = Test-FrontendReleaseReady -Port 5173 -ReleaseId $previous -Attempts 60
                if ($rollbackReady) {
                    Write-Host "RELEASE_ACTIVATION_ROLLBACK_OK active=$previous pid=$($rollbackProcess.Id)"
                }
            } catch {
                Write-Warning "Previous frontend release could not be restored: $($_.Exception.Message)"
                $rollbackReady = $false
            }
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
Write-Host "RELEASE_READY id=$releaseId sha=$fullSha path=$releasePath manifest=$releaseManifestPath previous=$previous"
