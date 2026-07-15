[CmdletBinding()]
param(
    [string]$RepoRoot = "",
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

if (-not (Test-Path (Join-Path $root "backend\main.py")) -or -not (Test-Path (Join-Path $root "start-public.bat"))) {
    throw "Refusing release outside the canonical project: $root"
}
$branch = (& git -C $root branch --show-current).Trim()
$sha = (& git -C $root rev-parse --short=12 HEAD).Trim()
$dirty = @(& git -C $root status --porcelain)
if ($branch -ne "main") { throw "Frontend releases are allowed only from main; current branch: $branch" }
if ($dirty.Count -gt 0 -and -not $PlanOnly) { throw "Refusing release from a dirty worktree." }
$releaseId = "$sha-$(Get-Date -Format 'yyyyMMddHHmmss')"
$releasePath = Join-Path $releases $releaseId

if ($PlanOnly) {
    Write-Host "RELEASE_PLAN root=$root branch=$branch sha=$sha"
    Write-Host "RELEASE_PLAN_STEP verify=$(-not $SkipVerify)"
    Write-Host "RELEASE_PLAN_STEP build=$releasePath"
    Write-Host "RELEASE_PLAN_STEP smoke_port=5197 routes=/,/feed,/gallery,/profile"
    Write-Host "RELEASE_PLAN_STEP atomic_manifest=$activeManifest retain=2"
    return
}

New-Item -ItemType Directory -Force -Path $releases | Out-Null
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    Push-Location $frontend
    try { & npm install; if ($LASTEXITCODE -ne 0) { throw "Frontend dependency install failed." } }
    finally { Pop-Location }
}
if (-not $SkipVerify) {
    & powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $root "tools\verify.ps1") -Mode Full -RepoRoot $root
    if ($LASTEXITCODE -ne 0) { throw "Release verification failed." }
}

New-Item -ItemType Directory -Force -Path $releasePath | Out-Null
Push-Location $frontend
try {
    $env:FRONTEND_BUILD_LABEL = $sha
    & npm run build -- --outDir $releasePath --emptyOutDir
    if ($LASTEXITCODE -ne 0) { throw "TypeScript or Vite release build failed." }
} finally { Pop-Location }

$releaseInfo = [ordered]@{ release_id = $releaseId; git_sha = $sha; built_at = (Get-Date).ToUniversalTime().ToString("o"); path = $releasePath }
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
$manifest = [ordered]@{ active_release = $releaseId; previous_release = $previous; release_path = $releasePath; git_sha = $sha; activated_at = (Get-Date).ToUniversalTime().ToString("o") }
$tempManifest = "$activeManifest.tmp"
$manifest | ConvertTo-Json | Set-Content -LiteralPath $tempManifest -Encoding utf8
Move-Item -LiteralPath $tempManifest -Destination $activeManifest -Force

$keep = @($releaseId, $previous) | Where-Object { $_ } | Select-Object -Unique
Get-ChildItem -LiteralPath $releases -Directory | Where-Object { $keep -notcontains $_.Name } | ForEach-Object {
    if ($_.FullName.StartsWith($releases, [StringComparison]::OrdinalIgnoreCase)) { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
}
Write-Host "RELEASE_READY id=$releaseId sha=$sha path=$releasePath previous=$previous"
