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
if ($PlanOnly) {
    Write-Host "CADDY_STOP_PLAN version=$($runtime.Version) port=$($runtime.ProductionPort) ownership=required frp=untouched"
    return
}
Assert-IzoCaddyRuntime -Runtime $runtime
$state = Get-IzoFrontendListenerState -Runtime $runtime -Port $runtime.ProductionPort
if ($state.Kind -eq "none") {
    Write-Host "CADDY_STOP_OK alreadyStopped=true"
    return
}
if ($state.Kind -ne "caddy") {
    throw "Refusing to stop an untrusted frontend listener: kind=$($state.Kind)"
}
$process = Get-Process -Id $state.Process.ProcessId -ErrorAction Stop
Stop-IzoCaddyProcess -Runtime $runtime -AdminAddress $runtime.ProductionAdminAddress -Process $process
if (-not (Wait-IzoFrontendPortFree -Port $runtime.ProductionPort)) {
    throw "Caddy production port did not become free after graceful stop."
}
Write-Host "CADDY_STOP_OK pid=$($state.Process.ProcessId) frp=untouched"
