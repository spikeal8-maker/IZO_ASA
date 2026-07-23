[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"

function Resolve-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    return [System.IO.Path]::GetFullPath($Path).TrimEnd("\")
}

function Stop-OwnedRole {
    param(
        [Parameter(Mandatory = $true)]$Role,
        [Parameter(Mandatory = $true)][string]$RoleName
    )

    $port = [int]$Role.port
    $expectedPath = Resolve-FullPath ([string]$Role.expected_command_path)
    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -eq 0) {
        Write-Host "LOCAL_TEST_STOP role=$RoleName state=not-listening"
        return
    }
    if ($listeners.Count -ne 1) {
        throw "Refusing to stop ${RoleName}: expected one listener on port $port, found $($listeners.Count)."
    }

    $listenerPid = [int]$listeners[0].OwningProcess
    if ($listenerPid -ne [int]$Role.listener_pid) {
        throw "Refusing to stop ${RoleName}: listener PID $listenerPid differs from recorded PID $($Role.listener_pid)."
    }

    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$listenerPid" -ErrorAction Stop
    $commandLine = [string]$process.CommandLine
    if ($commandLine.IndexOf($expectedPath, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw "Refusing to stop ${RoleName}: PID $listenerPid does not contain the recorded command path."
    }

    Stop-Process -Id $listenerPid -Force -ErrorAction Stop
    $launchPid = [int]$Role.launch_pid
    if ($launchPid -ne $listenerPid -and (Get-Process -Id $launchPid -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $launchPid -Force -ErrorAction Stop
    }
    Write-Host "LOCAL_TEST_STOP role=$RoleName pid=$listenerPid state=stopped"
}

$root = Resolve-FullPath $RepoRoot
$runtimeRoot = Join-Path $root ".runtime\local-test"
$manifestPath = Join-Path $runtimeRoot "stack.json"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    Write-Host "LOCAL_TEST_STACK_NOT_RUNNING manifest=$manifestPath"
    exit 0
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ((Resolve-FullPath ([string]$manifest.repo_root)) -ne $root) {
    throw "The local-test manifest belongs to a different repository root."
}

Stop-OwnedRole -Role $manifest.frontend -RoleName "frontend"
Stop-OwnedRole -Role $manifest.backend -RoleName "backend"

Remove-Item -LiteralPath $manifestPath -Force
Write-Host "LOCAL_TEST_STACK_STOPPED data_preserved=true runtime=$runtimeRoot"
