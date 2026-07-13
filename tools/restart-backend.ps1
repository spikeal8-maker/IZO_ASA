[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonPath = "",
    [string]$BindAddress = "127.0.0.1",
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [ValidateRange(5, 300)]
    [int]$StartupTimeoutSeconds = 60,
    [ValidateRange(1, 60)]
    [int]$StopTimeoutSeconds = 15,
    [ValidateRange(1, 60)]
    [int]$HealthProbeTimeoutSeconds = 10,
    [string]$LogDirectory = "",
    [switch]$ValidateOnly,
    [switch]$PreflightOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($ValidateOnly -and $PreflightOnly) {
    throw "ValidateOnly and PreflightOnly are mutually exclusive."
}
if ($BindAddress -ne "127.0.0.1") {
    throw "Backend restart is restricted to 127.0.0.1; requested bind: $BindAddress"
}

function Resolve-PythonExecutable {
    param([string]$RequestedPath)

    if ($RequestedPath.Trim()) {
        $requested = $RequestedPath.Trim()
        if (Test-Path -LiteralPath $requested -PathType Leaf) {
            return (Resolve-Path -LiteralPath $requested).Path
        }
        throw "Requested Python executable was not found: $requested"
    }
    if ($env:IZO_PYTHON_PATH -and $env:IZO_PYTHON_PATH.Trim()) {
        $configured = $env:IZO_PYTHON_PATH.Trim()
        if (Test-Path -LiteralPath $configured -PathType Leaf) {
            return (Resolve-Path -LiteralPath $configured).Path
        }
        throw "IZO_PYTHON_PATH executable was not found: $configured"
    }
    $defaultPython = "C:\Program Files\Python311\python.exe"
    if (Test-Path -LiteralPath $defaultPython -PathType Leaf) {
        return (Resolve-Path -LiteralPath $defaultPython).Path
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $command -and $command.Source) {
        return $command.Source
    }
    throw "Python executable was not found. Set -PythonPath or IZO_PYTHON_PATH."
}

function Assert-BackendCommand {
    param(
        [string]$CommandLine,
        [int]$ExpectedPort,
        [string]$ExpectedBind
    )

    $hostPattern = [regex]::Escape($ExpectedBind)
    $portPattern = [regex]::Escape([string]$ExpectedPort)
    if ($CommandLine -notmatch "(?i)(?:^|\s)-m\s+uvicorn\s+main:app(?:\s|$)") {
        throw "Port $ExpectedPort is not owned by the expected uvicorn main:app command."
    }
    if ($CommandLine -notmatch "(?i)--host\s+$hostPattern(?:\s|$)") {
        throw "Backend command does not bind to $ExpectedBind."
    }
    if ($CommandLine -notmatch "(?i)--port\s+$portPattern(?:\s|$)") {
        throw "Backend command does not use port $ExpectedPort."
    }
}

function Get-BackendState {
    param(
        [int]$ExpectedPort,
        [string]$ExpectedBind,
        [string]$ExpectedPython
    )

    $listeners = @(Get-NetTCPConnection -LocalPort $ExpectedPort -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -ne 1) {
        throw "Expected exactly one listener on port $ExpectedPort; found $($listeners.Count)."
    }
    $listener = $listeners[0]
    if ($listener.LocalAddress -ne $ExpectedBind) {
        throw "Backend listener is $($listener.LocalAddress):$ExpectedPort, expected ${ExpectedBind}:$ExpectedPort."
    }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
    if ($null -eq $process) {
        throw "Listener PID $($listener.OwningProcess) could not be inspected."
    }
    Assert-BackendCommand -CommandLine ([string]$process.CommandLine) -ExpectedPort $ExpectedPort -ExpectedBind $ExpectedBind
    if ($process.ExecutablePath) {
        $actualPython = [System.IO.Path]::GetFullPath([string]$process.ExecutablePath)
        $requiredPython = [System.IO.Path]::GetFullPath($ExpectedPython)
        if (-not $actualPython.Equals($requiredPython, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Backend uses an unexpected Python executable: $actualPython"
        }
    }
    return [pscustomobject]@{
        ProcessId = [int]$listener.OwningProcess
        Address = [string]$listener.LocalAddress
        CommandLine = [string]$process.CommandLine
    }
}

function Test-BackendHealth {
    param(
        [string]$Uri,
        [int]$TimeoutSeconds
    )

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec $TimeoutSeconds
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Write-LogTail {
    param(
        [string]$Label,
        [string]$Path
    )

    Write-Host "--- ${Label}: $Path ---"
    if (Test-Path -LiteralPath $Path) {
        Get-Content -LiteralPath $Path -Tail 80 -ErrorAction SilentlyContinue | Write-Host
    } else {
        Write-Host "log file was not created"
    }
}

$resolvedRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$backendDirectory = Join-Path -Path $resolvedRoot -ChildPath "backend"
$mainFile = Join-Path -Path $backendDirectory -ChildPath "main.py"
if (-not (Test-Path -LiteralPath $mainFile -PathType Leaf)) {
    throw "Backend entrypoint not found: $mainFile"
}
$pythonExecutable = Resolve-PythonExecutable -RequestedPath $PythonPath
$healthUri = "http://$BindAddress`:$Port/api/health"

Push-Location -LiteralPath $backendDirectory
try {
    $preflightOutput = @(& $pythonExecutable -c "import main; assert getattr(main, 'app', None) is not None" 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Backend import preflight failed: $($preflightOutput -join [Environment]::NewLine)"
    }
} finally {
    Pop-Location
}

if ($ValidateOnly) {
    Write-Host "BACKEND_RESTART_VALIDATE_OK root=$resolvedRoot python=$pythonExecutable bind=$BindAddress port=$Port"
    return
}

$oldState = Get-BackendState -ExpectedPort $Port -ExpectedBind $BindAddress -ExpectedPython $pythonExecutable
if (-not (Test-BackendHealth -Uri $healthUri -TimeoutSeconds $HealthProbeTimeoutSeconds)) {
    throw "Current backend failed health preflight: $healthUri"
}

if ($PreflightOnly) {
    Write-Host "BACKEND_RESTART_PREFLIGHT_OK pid=$($oldState.ProcessId) bind=$($oldState.Address) port=$Port"
    return
}

if (-not $LogDirectory.Trim()) {
    $LogDirectory = Join-Path -Path $resolvedRoot -ChildPath "logs"
}
[System.IO.Directory]::CreateDirectory($LogDirectory) | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
$stdoutLog = Join-Path -Path $LogDirectory -ChildPath "backend_restart_$timestamp.out.log"
$stderrLog = Join-Path -Path $LogDirectory -ChildPath "backend_restart_$timestamp.err.log"

Write-Host "Stopping backend PID $($oldState.ProcessId) on $BindAddress`:$Port..."
Stop-Process -Id $oldState.ProcessId -ErrorAction Stop
$stopDeadline = (Get-Date).AddSeconds($StopTimeoutSeconds)
while ((Get-Process -Id $oldState.ProcessId -ErrorAction SilentlyContinue) -and (Get-Date) -lt $stopDeadline) {
    Start-Sleep -Milliseconds 250
}
if (Get-Process -Id $oldState.ProcessId -ErrorAction SilentlyContinue) {
    Write-Warning "Backend did not stop within $StopTimeoutSeconds seconds; forcing PID $($oldState.ProcessId)."
    Stop-Process -Id $oldState.ProcessId -Force -ErrorAction Stop
}
$portDeadline = (Get-Date).AddSeconds($StopTimeoutSeconds)
while ((Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) -and (Get-Date) -lt $portDeadline) {
    Start-Sleep -Milliseconds 250
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $Port did not become free after stopping PID $($oldState.ProcessId)."
}

$newProcess = $null
try {
    $newProcess = Start-Process `
        -FilePath $pythonExecutable `
        -ArgumentList @("-m", "uvicorn", "main:app", "--host", $BindAddress, "--port", [string]$Port) `
        -WorkingDirectory $backendDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru

    $startupDeadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    $healthy = $false
    while ((Get-Date) -lt $startupDeadline) {
        if ($newProcess.HasExited) {
            break
        }
        if (Test-BackendHealth -Uri $healthUri -TimeoutSeconds $HealthProbeTimeoutSeconds) {
            $healthy = $true
            break
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $healthy) {
        throw "New backend did not pass health within $StartupTimeoutSeconds seconds."
    }

    $newState = Get-BackendState -ExpectedPort $Port -ExpectedBind $BindAddress -ExpectedPython $pythonExecutable
    if ($newState.ProcessId -ne $newProcess.Id) {
        throw "Listener PID $($newState.ProcessId) does not match started PID $($newProcess.Id)."
    }
    Write-Host "BACKEND_RESTART_OK oldPid=$($oldState.ProcessId) newPid=$($newState.ProcessId) health=200 bind=$BindAddress port=$Port"
    Write-Host "stdout=$stdoutLog"
    Write-Host "stderr=$stderrLog"
} catch {
    Write-Error "BACKEND_RESTART_FAILED: $($_.Exception.Message)"
    Write-LogTail -Label "stdout" -Path $stdoutLog
    Write-LogTail -Label "stderr" -Path $stderrLog
    if ($null -ne $newProcess -and -not $newProcess.HasExited) {
        Stop-Process -Id $newProcess.Id -Force -ErrorAction SilentlyContinue
    }
    throw
}
