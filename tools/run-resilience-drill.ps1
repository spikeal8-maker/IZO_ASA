[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$LiveBaseUrl = "",
    [switch]$PlanOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path) }
$root = (Resolve-Path -LiteralPath $RepoRoot).Path
if (-not (Test-Path (Join-Path $root "backend\main.py")) -or -not (Test-Path (Join-Path $root "start-public.bat"))) { throw "Drills are allowed only in the canonical project." }
$scenarios = @("malformed-gallery-contract", "isolated-studio-form", "isolated-preview", "isolated-history", "backend-unavailable", "auth-401", "failed-candidate-release")
if ($PlanOnly) {
    Write-Host "DRILL_PLAN root=$root scenarios=$($scenarios -join ',')"
    Write-Host "DRILL_PLAN_STEP npm=e2e:studio-resilience"
    if ($LiveBaseUrl) { Write-Host "DRILL_PLAN_STEP synthetic=$LiveBaseUrl" }
    return
}

$started = Get-Date
Push-Location (Join-Path $root "frontend")
try {
    & npm run e2e:studio-resilience
    if ($LASTEXITCODE -ne 0) { throw "Studio resilience drill failed." }
    if ($LiveBaseUrl) {
        $env:IZO_SYNTHETIC_BASE_URL = $LiveBaseUrl
        & npm run e2e:synthetic
        if ($LASTEXITCODE -ne 0) { throw "Live synthetic drill failed." }
    }
} finally { Pop-Location }

$output = Join-Path $root ".runtime\drills"
New-Item -ItemType Directory -Force -Path $output | Out-Null
$report = [ordered]@{ ok = $true; started_at = $started.ToUniversalTime().ToString("o"); completed_at = (Get-Date).ToUniversalTime().ToString("o"); scenarios = $scenarios; live_base_url = $LiveBaseUrl }
$path = Join-Path $output "$(Get-Date -Format 'yyyyMMdd_HHmmss').json"
$report | ConvertTo-Json | Set-Content -LiteralPath $path -Encoding utf8
Write-Host "DRILL_OK report=$path"
