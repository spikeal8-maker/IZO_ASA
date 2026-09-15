[CmdletBinding()]
param([string]$RepoRoot = "")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $RepoRoot.Trim()) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$gitCommand = Get-Command git.exe -ErrorAction SilentlyContinue
if ($null -eq $gitCommand) { $gitCommand = Get-Command git -ErrorAction Stop }

foreach ($name in @("pre-push", "pre-commit")) {
    $hook = Join-Path (Join-Path $RepoRoot ".githooks") $name
    if (-not (Test-Path -LiteralPath $hook -PathType Leaf)) {
        throw "Required versioned hook is missing: $hook"
    }
}

$existing = (& $gitCommand.Source -C $RepoRoot config --get core.hooksPath 2>$null)
$existingExit = $LASTEXITCODE
if ($existingExit -notin @(0, 1)) { throw "Failed to inspect effective core.hooksPath." }
if ($existingExit -eq 0 -and ([string]$existing).Trim() -and ([string]$existing).Trim() -ne ".githooks") {
    throw "AGENT_HOOKS_PATH_CONFLICT existing=$(([string]$existing).Trim())"
}
& $gitCommand.Source -C $RepoRoot config --local core.hooksPath .githooks
if ($LASTEXITCODE -ne 0) { throw "Failed to configure repository-local core.hooksPath." }
$configured = (& $gitCommand.Source -C $RepoRoot config --local --get core.hooksPath).Trim()
if ($LASTEXITCODE -ne 0 -or $configured -ne ".githooks") {
    throw "Repository-local core.hooksPath verification failed."
}
Write-Host "AGENT_HOOKS_INSTALLED path=.githooks"
