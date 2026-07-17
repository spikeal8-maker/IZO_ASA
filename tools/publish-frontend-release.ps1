[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$PythonPath = "",
    [switch]$SkipVerify,
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
$projectPython = Join-Path $root "backend\.venv\Scripts\python.exe"
if ($PythonPath.Trim()) {
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw "Requested release Python was not found." }
    $python = (Resolve-Path -LiteralPath $PythonPath).Path
} else {
    $python = $projectPython
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
    Write-Host "RELEASE_PLAN_STEP verify=$(-not $SkipVerify)"
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

New-Item -ItemType Directory -Force -Path $releases | Out-Null
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    Push-Location $frontend
    try { & npm install; if ($LASTEXITCODE -ne 0) { throw "Frontend dependency install failed." } }
    finally { Pop-Location }
}
if (-not $SkipVerify) {
    & powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $root "tools\verify.ps1") -Mode Full -RepoRoot $root -PythonPath $python
    if ($LASTEXITCODE -ne 0) { throw "Release verification failed." }
}

New-Item -ItemType Directory -Force -Path $releasePath | Out-Null
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
$releaseInfo = [ordered]@{ release_id = $releaseId; git_sha = $fullSha; built_at = $builtAt; path = $releasePath; release_manifest = $releaseManifestPath }
$releaseInfo | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $releasePath "release.json") -Encoding utf8

$vite = Join-Path $frontend "node_modules\vite\bin\vite.js"
$preview = Start-Process -FilePath "node.exe" -ArgumentList @("`"$vite`"", "preview", "--host", "127.0.0.1", "--port", "5197", "--strictPort", "--outDir", "`"$releasePath`"") -WorkingDirectory $frontend -WindowStyle Hidden -PassThru
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
    if ($releasePath.StartsWith($releases, [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $releasePath -Recurse -Force -ErrorAction SilentlyContinue
    }
    throw
} finally {
    Stop-Process -Id $preview.Id -Force -ErrorAction SilentlyContinue
}

$previous = $null
if (Test-Path $activeManifest) {
    $previous = (Get-Content $activeManifest -Raw | ConvertFrom-Json).active_release
}
$manifest = [ordered]@{ active_release = $releaseId; previous_release = $previous; release_path = $releasePath; release_manifest = $releaseManifestPath; git_sha = $fullSha; activated_at = (Get-Date).ToUniversalTime().ToString("o") }
$tempManifest = "$activeManifest.tmp"
$manifest | ConvertTo-Json | Set-Content -LiteralPath $tempManifest -Encoding utf8
Move-Item -LiteralPath $tempManifest -Destination $activeManifest -Force

$listener = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
    if ($process.CommandLine -notmatch "vite.+preview" -or $process.CommandLine -notlike "*$root*") {
        throw "Port 5173 is not owned by the canonical Vite preview; refusing to stop it."
    }
    Stop-Process -Id $listener.OwningProcess -Force
}
Start-Process -FilePath "node.exe" -ArgumentList @("`"$vite`"", "preview", "--host", "127.0.0.1", "--port", "5173", "--strictPort", "--outDir", "`"$releasePath`"") -WorkingDirectory $frontend -WindowStyle Hidden | Out-Null
$productionReady = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        if ((Invoke-WebRequest "http://127.0.0.1:5173/" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) {
            $productionReady = $true
            break
        }
    } catch {}
    Start-Sleep -Seconds 1
}
if (-not $productionReady) {
    throw "Activated frontend preview did not become ready on port 5173."
}

$keep = @($releaseId, $previous) | Where-Object { $_ } | Select-Object -Unique
Get-ChildItem -LiteralPath $releases -Directory | Where-Object { $keep -notcontains $_.Name } | ForEach-Object {
    if ($_.FullName.StartsWith($releases, [StringComparison]::OrdinalIgnoreCase)) { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
}
Write-Host "RELEASE_READY id=$releaseId sha=$fullSha path=$releasePath manifest=$releaseManifestPath previous=$previous"
