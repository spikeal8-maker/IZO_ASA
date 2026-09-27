[CmdletBinding()]
param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet("doctor", "start", "status", "scope-add", "finish", "main-guard", "context", "sandbox", "symbol", "env-up", "env-status", "env-down", "verify", "audit", "eval")]
    [string]$Command,
    [string]$Manifest = "",
    [string]$Path = "",
    [string]$Symbol = "",
    [string]$Reason = "",
    [string]$Ref = "",
    [string]$Domain = "",
    [ValidateSet("build", "probe", "run")]
    [string]$SandboxAction = "",
    [string]$SandboxCommand = "",
    [switch]$SandboxInteractive,
    [switch]$RecoverStale,
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

if ($Command -eq "main-guard") {
    if (-not $Ref.Trim()) { throw "-Ref is required for agent main-guard." }
    Push-Location -LiteralPath $RepoRoot
    try {
        & $python -m tools.agent_system.main_guard check-target --ref $Ref
        exit $LASTEXITCODE
    } finally {
        Pop-Location
    }
}

if ($Command -eq "verify") {
    Push-Location -LiteralPath $RepoRoot
    try {
        & $python -m tools.agent_system.enforce --repo-root $RepoRoot local
        exit $LASTEXITCODE
    } finally {
        Pop-Location
    }
}

if ($Command -eq "context") {
    if (-not $Domain.Trim()) { throw "-Domain is required for agent context." }
    Push-Location -LiteralPath $RepoRoot
    try {
        & $python -m tools.agent_system.context --repo-root $RepoRoot --domain $Domain
        exit $LASTEXITCODE
    } finally {
        Pop-Location
    }
}

if ($Command -eq "symbol") {
    if (-not $Path.Trim()) { throw "-Path is required for agent symbol." }
    if (-not $Symbol.Trim()) { throw "-Symbol is required for agent symbol." }
    Push-Location -LiteralPath $RepoRoot
    try {
        & $python -m tools.agent_system.symbol --repo-root $RepoRoot --path $Path --symbol $Symbol
        exit $LASTEXITCODE
    } finally {
        Pop-Location
    }
}

if ($Command -eq "sandbox") {
    if (-not $SandboxAction.Trim()) { throw "-SandboxAction is required for agent sandbox." }
    $sandboxArguments = @("-m", "tools.agent_system.sandbox", "--repo-root", $RepoRoot, $SandboxAction)
    if ($SandboxAction -eq "run") {
        if ($SandboxCommand.Trim()) {
            $commandBytes = [Text.Encoding]::UTF8.GetBytes($SandboxCommand)
            $commandBase64 = [Convert]::ToBase64String($commandBytes)
            $sandboxArguments += @("--command-base64", $commandBase64)
        }
        if ($SandboxInteractive) { $sandboxArguments += "--interactive" }
    } elseif ($SandboxCommand.Trim() -or $SandboxInteractive) {
        throw "-SandboxCommand/-SandboxInteractive are valid only with -SandboxAction run."
    }
    Push-Location -LiteralPath $RepoRoot
    try {
        & $python @sandboxArguments
        exit $LASTEXITCODE
    } finally {
        Pop-Location
    }
}

if ($RecoverStale -and $Command -ne "env-down") {
    throw "-RecoverStale is valid only with agent env-down."
}

if ($Command -in @("env-up", "env-status", "env-down")) {
    $lifecycleCommand = switch ($Command) {
        "env-up" { "up" }
        "env-status" { "status" }
        "env-down" { "down" }
    }
    $lifecycleArguments = @(
        "-m", "tools.agent_system.env_lifecycle",
        "--repo-root", $RepoRoot,
        $lifecycleCommand
    )
    if ($Command -eq "env-down" -and $RecoverStale) {
        $lifecycleArguments += "--recover-stale"
    }
    Push-Location -LiteralPath $RepoRoot
    try {
        & $python @lifecycleArguments
        exit $LASTEXITCODE
    } finally {
        Pop-Location
    }
}

if ($Command -eq "status") {
    Push-Location -LiteralPath $RepoRoot
    try {
        & $python -m tools.agent_system.package --repo-root $RepoRoot status
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        $ownership = Join-Path $RepoRoot ".runtime\agent\ownership.json"
        if (Test-Path -LiteralPath $ownership -PathType Leaf) {
            & $python -m tools.agent_system.env_lifecycle --repo-root $RepoRoot status
            exit $LASTEXITCODE
        }
        exit 0
    } finally {
        Pop-Location
    }
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
