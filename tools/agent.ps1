[CmdletBinding()]
param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet("doctor", "start", "status", "scope-add", "finish", "context", "symbol", "env-up", "verify", "audit", "eval")]
    [string]$Command,
    [string]$Manifest = "",
    [string]$Path = "",
    [string]$Reason = "",
    [string]$WorktreePath = "",
    [string]$RepoRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)

if (-not $RepoRoot.Trim()) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$projectPython = Join-Path $RepoRoot "backend\.venv\Scripts\python.exe"
if (Test-Path -LiteralPath $projectPython -PathType Leaf) {
    $python = $projectPython
} else {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        $pythonCommand = Get-Command python -ErrorAction Stop
    }
    $python = $pythonCommand.Source
}

$arguments = @("-m", "tools.agent_system.package", "--repo-root", $RepoRoot, $Command)
switch ($Command) {
    "start" {
        if (-not $Manifest.Trim()) { throw "-Manifest is required for agent start." }
        $arguments += @("--manifest", $Manifest)
        if ($WorktreePath.Trim()) { $arguments += @("--worktree-path", $WorktreePath) }
    }
    "scope-add" {
        if (-not $Path.Trim()) { throw "-Path is required for agent scope-add." }
        if (-not $Reason.Trim()) { throw "-Reason is required for agent scope-add." }
        $arguments += @("--path", $Path, "--reason", $Reason)
    }
}
Push-Location -LiteralPath $RepoRoot
try {
    & $python @arguments
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
