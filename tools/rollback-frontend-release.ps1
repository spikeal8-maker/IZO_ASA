[CmdletBinding()]
param(
    [string]$ReleaseId = "",
    [string]$RepoRoot = "",
    [switch]$PlanOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path) }
$root = (Resolve-Path -LiteralPath $RepoRoot).Path
$manifestPath = Join-Path $root ".runtime\active-frontend.json"
if (-not (Test-Path (Join-Path $root "backend\main.py")) -or -not (Test-Path $manifestPath)) { throw "Canonical active release manifest was not found." }
$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
if (-not $ReleaseId) { $ReleaseId = [string]$manifest.previous_release }
if (-not $ReleaseId) { throw "No previous release is available." }
$target = Join-Path $root ".runtime\releases\frontend\$ReleaseId"
if (-not (Test-Path (Join-Path $target "index.html"))) { throw "Release is incomplete: $ReleaseId" }
if ($PlanOnly) { Write-Host "ROLLBACK_PLAN target=$ReleaseId path=$target smoke=5197 restart=5173"; return }

$frontend = Join-Path $root "frontend"
$vite = Join-Path $frontend "node_modules\vite\bin\vite.js"
$preview = Start-Process -FilePath "node.exe" -ArgumentList @("`"$vite`"", "preview", "--host", "127.0.0.1", "--port", "5197", "--strictPort", "--outDir", "`"$target`"") -WorkingDirectory $frontend -WindowStyle Hidden -PassThru
try {
    for ($i = 0; $i -lt 40; $i++) {
        try { if ((Invoke-WebRequest "http://127.0.0.1:5197/" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { break } } catch {}
        if ($i -eq 39) { throw "Rollback candidate did not become ready." }
        Start-Sleep -Milliseconds 500
    }
    Push-Location $frontend
    try { $env:IZO_SYNTHETIC_BASE_URL = "http://127.0.0.1:5197"; & npm run e2e:synthetic; if ($LASTEXITCODE -ne 0) { throw "Rollback smoke failed." } }
    finally { Pop-Location }
} finally { Stop-Process -Id $preview.Id -Force -ErrorAction SilentlyContinue }

$oldActive = [string]$manifest.active_release
$releaseInfo = Get-Content (Join-Path $target "release.json") -Raw | ConvertFrom-Json
$next = [ordered]@{ active_release = $ReleaseId; previous_release = $oldActive; release_path = $target; git_sha = $releaseInfo.git_sha; activated_at = (Get-Date).ToUniversalTime().ToString("o"); rollback = $true }
$temp = "$manifestPath.tmp"
$next | ConvertTo-Json | Set-Content -LiteralPath $temp -Encoding utf8
Move-Item -LiteralPath $temp -Destination $manifestPath -Force

$listener = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
    if ($process.CommandLine -notmatch "vite.+preview" -or $process.CommandLine -notlike "*$root*") { throw "Port 5173 is not owned by the canonical Vite preview; refusing to stop it." }
    Stop-Process -Id $listener.OwningProcess -Force
}
Start-Process -FilePath "node.exe" -ArgumentList @("`"$vite`"", "preview", "--host", "127.0.0.1", "--port", "5173", "--strictPort", "--outDir", "`"$target`"") -WorkingDirectory $frontend -WindowStyle Hidden | Out-Null
for ($i = 0; $i -lt 30; $i++) {
    try { if ((Invoke-WebRequest "http://127.0.0.1:5173/" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { Write-Host "ROLLBACK_OK active=$ReleaseId previous=$oldActive"; exit 0 } } catch {}
    Start-Sleep -Seconds 1
}
throw "Rolled-back preview did not become ready on port 5173."
