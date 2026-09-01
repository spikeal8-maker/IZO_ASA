[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$PythonPath = "",
    [string]$ReleaseManifestPath = "",
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
    [switch]$PreflightOnly,
    [switch]$AllowColdStart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$serviceOwnershipScript = Join-Path $PSScriptRoot "backend-service-ownership.ps1"
$installedReleaseRoot = "C:\IZO_ASA\releases"
$installedServiceBasePython = "C:\IZO_ASA\runtime\python311\python.exe"
if (-not (Test-Path -LiteralPath $serviceOwnershipScript -PathType Leaf)) {
    throw "Backend service ownership helper was not found: $serviceOwnershipScript"
}
. $serviceOwnershipScript

if (-not $RepoRoot.Trim()) {
    $scriptPath = [string]$MyInvocation.MyCommand.Path
    if (-not $scriptPath.Trim()) {
        throw "Restart script path could not be resolved. Pass -RepoRoot explicitly."
    }
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $scriptPath)
}

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
        [string]$ExpectedBind,
        [switch]$RequireProxyIsolation
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
    if ($RequireProxyIsolation -and $CommandLine -notmatch "(?i)(?:^|\s)--no-proxy-headers(?:\s|$)") {
        throw "Backend command does not disable Uvicorn proxy-header rewriting."
    }
}

function Get-BackendState {
    param(
        [int]$ExpectedPort,
        [string]$ExpectedBind,
        [string]$ExpectedPython,
        [switch]$RequireProxyIsolation,
        [switch]$AllowOpaqueServiceProcess,
        [switch]$AllowInstalledServiceProcess
    )

    $listeners = @(Get-NetTCPConnection -LocalPort $ExpectedPort -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -ne 1) {
        throw "Expected exactly one listener on port $ExpectedPort; found $($listeners.Count)."
    }
    $listener = $listeners[0]
    if ($listener.LocalAddress -ne $ExpectedBind) {
        throw "Backend listener is $($listener.LocalAddress):$ExpectedPort, expected ${ExpectedBind}:$ExpectedPort."
    }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
    if ($null -eq $process -or -not $process.CommandLine -or -not $process.ExecutablePath) {
        if (-not $AllowOpaqueServiceProcess) {
            throw "Listener PID $($listener.OwningProcess) could not be inspected."
        }
        $service = Get-Service -Name "IZOBackend" -ErrorAction SilentlyContinue
        if ($null -eq $service -or $service.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Running) {
            throw "Backend listener metadata is opaque and the IZOBackend service is not running."
        }
        return [pscustomobject]@{
            ProcessId = [int]$listener.OwningProcess
            RuntimeLauncherProcessId = [int]$listener.OwningProcess
            RuntimeLauncherExecutablePath = ""
            RuntimeOwnership = "opaque-service-health-verified"
            Address = [string]$listener.LocalAddress
            CommandLine = ""
            ExecutablePath = ""
            ProxyHeadersDisabled = $null
        }
    }
    Assert-BackendCommand -CommandLine ([string]$process.CommandLine) -ExpectedPort $ExpectedPort -ExpectedBind $ExpectedBind -RequireProxyIsolation:$RequireProxyIsolation
    $runtimeLauncherProcessId = [int]$listener.OwningProcess
    $runtimeLauncherExecutablePath = [string]$process.ExecutablePath
    $runtimeOwnership = "unchecked-listener"
    if ($ExpectedPython.Trim()) {
        if (-not $process.ExecutablePath) {
            throw "Backend listener executable path could not be inspected."
        }
        $actualPython = [System.IO.Path]::GetFullPath([string]$process.ExecutablePath)
        $requiredPython = [System.IO.Path]::GetFullPath($ExpectedPython)
        if ($actualPython.Equals($requiredPython, [System.StringComparison]::OrdinalIgnoreCase)) {
            $runtimeOwnership = "direct-python"
        } else {
            if (-not [System.IO.Path]::GetFileName($actualPython).Equals("python.exe", [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "Backend listener is not a Python executable: $actualPython"
            }
            $launcherProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.ParentProcessId)" -ErrorAction SilentlyContinue
            if ($null -eq $launcherProcess -or -not $launcherProcess.ExecutablePath) {
                throw "Backend listener parent process could not be inspected for project virtual-environment ownership."
            }
            $launcherPython = [System.IO.Path]::GetFullPath([string]$launcherProcess.ExecutablePath)
            if (-not $launcherPython.Equals($requiredPython, [System.StringComparison]::OrdinalIgnoreCase)) {
                if (-not $AllowInstalledServiceProcess) {
                    throw "Backend uses an unexpected Python process chain: listener=$actualPython parent=$launcherPython"
                }
                $service = Get-CimInstance Win32_Service -Filter "Name='IZOBackend'" -ErrorAction SilentlyContinue
                if ($null -eq $service) {
                    throw "Backend uses an unexpected Python process chain and the IZOBackend service could not be inspected."
                }
                $installedOwnership = Assert-IzoInstalledBackendServiceOwnership `
                    -ListenerProcess $process `
                    -LauncherProcess $launcherProcess `
                    -Service $service `
                    -ExpectedReleaseRoot $installedReleaseRoot `
                    -ExpectedBasePython $installedServiceBasePython
                Assert-BackendCommand -CommandLine ([string]$launcherProcess.CommandLine) -ExpectedPort $ExpectedPort -ExpectedBind $ExpectedBind -RequireProxyIsolation:$RequireProxyIsolation
                $runtimeLauncherProcessId = [int]$installedOwnership.RuntimeLauncherProcessId
                $runtimeLauncherExecutablePath = [string]$installedOwnership.RuntimeLauncherExecutablePath
                $runtimeOwnership = [string]$installedOwnership.RuntimeOwnership
                return [pscustomobject]@{
                    ProcessId = [int]$listener.OwningProcess
                    RuntimeLauncherProcessId = $runtimeLauncherProcessId
                    RuntimeLauncherExecutablePath = $runtimeLauncherExecutablePath
                    RuntimeOwnership = $runtimeOwnership
                    Address = [string]$listener.LocalAddress
                    CommandLine = [string]$process.CommandLine
                    ExecutablePath = [string]$process.ExecutablePath
                    ProxyHeadersDisabled = [bool]($process.CommandLine -match "(?i)(?:^|\s)--no-proxy-headers(?:\s|$)")
                }
            }
            Assert-BackendCommand -CommandLine ([string]$launcherProcess.CommandLine) -ExpectedPort $ExpectedPort -ExpectedBind $ExpectedBind -RequireProxyIsolation:$RequireProxyIsolation
            $runtimeLauncherProcessId = [int]$launcherProcess.ProcessId
            $runtimeLauncherExecutablePath = [string]$launcherProcess.ExecutablePath
            $runtimeOwnership = "windows-venv-child"
        }
    }
    return [pscustomobject]@{
        ProcessId = [int]$listener.OwningProcess
        RuntimeLauncherProcessId = $runtimeLauncherProcessId
        RuntimeLauncherExecutablePath = $runtimeLauncherExecutablePath
        RuntimeOwnership = $runtimeOwnership
        Address = [string]$listener.LocalAddress
        CommandLine = [string]$process.CommandLine
        ExecutablePath = [string]$process.ExecutablePath
        ProxyHeadersDisabled = [bool]($process.CommandLine -match "(?i)(?:^|\s)--no-proxy-headers(?:\s|$)")
    }
}

function Test-BackendHealth {
    param(
        [string]$Uri,
        [int]$TimeoutSeconds
    )

    try {
        $response = Invoke-RestMethod -Uri $Uri -TimeoutSec $TimeoutSeconds
        if ($response.PSObject.Properties.Name -contains "ready" -and $response.ready -ne $true) {
            return $false
        }
        return $response.ok -eq $true
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

function Invoke-WithProcessEnvironment {
    param(
        [hashtable]$Values,
        [scriptblock]$Action
    )

    $previous = @{}
    foreach ($name in $Values.Keys) {
        $previous[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
        [Environment]::SetEnvironmentVariable($name, [string]$Values[$name], "Process")
    }
    try {
        & $Action
    } finally {
        foreach ($name in $Values.Keys) {
            [Environment]::SetEnvironmentVariable($name, $previous[$name], "Process")
        }
    }
}

function Get-ProductionReleaseContract {
    param(
        [string]$RequestedManifest,
        [string]$Root,
        [string]$BackendDirectory
    )

    if (-not $RequestedManifest.Trim()) {
        throw "ReleaseManifestPath is required for an actual production restart."
    }
    $manifestPath = (Resolve-Path -LiteralPath $RequestedManifest -ErrorAction Stop).Path
    $allowedRoot = (Resolve-Path -LiteralPath (Join-Path $Root ".runtime\releases\frontend") -ErrorAction Stop).Path
    if (-not $manifestPath.StartsWith($allowedRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Release manifest must be inside the canonical runtime release directory."
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $releaseId = [string]$manifest.release_id
    $gitSha = [string]$manifest.git_sha
    if ($manifest.manifest_version -ne 1 -or $releaseId -notmatch "^[0-9a-f]{12}-[0-9]{14}$" -or $gitSha -notmatch "^[0-9a-f]{40}$" -or $manifest.dirty -ne $false) {
        throw "Release manifest identity is invalid."
    }
    $head = ([string](@(& git.exe -C $Root rev-parse HEAD)[0])).Trim()
    if ($LASTEXITCODE -ne 0 -or $head -ne $gitSha) {
        throw "Release manifest does not match the current checkout."
    }
    if (@(& git.exe -C $Root status --porcelain).Count -gt 0) {
        throw "Refusing production restart from a dirty checkout."
    }
    $databasePath = Join-Path $BackendDirectory "onenode.sqlite3"
    $telegramMode = if ($env:BOT_UPDATES_MODE -and $env:BOT_UPDATES_MODE.Trim()) { $env:BOT_UPDATES_MODE.Trim() } else { "polling" }
    $maxMode = if ($env:MAX_UPDATES_MODE -and $env:MAX_UPDATES_MODE.Trim()) { $env:MAX_UPDATES_MODE.Trim() } else { "polling" }
    $maxApiBaseUrl = if ($env:MAX_API_BASE_URL -and $env:MAX_API_BASE_URL.Trim()) { $env:MAX_API_BASE_URL.Trim() } else { "https://platform-api2.max.ru" }
    return [pscustomobject]@{
        ManifestPath = $manifestPath
        ReleaseId = $releaseId
        GitSha = $gitSha
        Environment = @{
            APP_ENV = "production"
            IZO_RUNTIME_PROFILE = "production"
            IZO_RELEASE_MANIFEST = $manifestPath
            APP_BUILD = $releaseId
            FRONTEND_BUILD_LABEL = $releaseId
            DATABASE_URL = "sqlite:///" + $databasePath.Replace("\", "/")
            DB_GUARD_ALLOWED_PATHS = $databasePath
            DB_GUARD_MIN_SIZE_MB = "10"
            DB_GUARD_MIN_USERS = "5"
            DB_GUARD_MIN_ACTIVE_ADMINS = "1"
            TRUSTED_COOKIE_SECURE = "true"
            TRUSTED_COOKIE_SAMESITE = "none"
            TRUSTED_COOKIE_PATH = "/"
            TRUST_CLOUDFLARE_HEADERS = "true"
            TRUST_PROXY_HEADERS = "true"
            BOT_UPDATES_MODE = $telegramMode
            MAX_UPDATES_MODE = $maxMode
            MAX_API_BASE_URL = $maxApiBaseUrl
        }
    }
}

function Test-BackendReleaseIdentity {
    param(
        [string]$Uri,
        [string]$ExpectedRelease,
        [string]$ExpectedGitSha,
        [int]$TimeoutSeconds
    )

    try {
        $payload = Invoke-RestMethod -Uri $Uri -TimeoutSec $TimeoutSeconds
        return (
            [string]$payload.release_id -eq $ExpectedRelease -and
            [string]$payload.frontend_build -eq $ExpectedRelease -and
            [string]$payload.backend_commit -eq $ExpectedGitSha
        )
    } catch {
        return $false
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
$versionUri = "http://$BindAddress`:$Port/api/version"
$actualRestart = -not $ValidateOnly -and -not $PreflightOnly
$releaseContract = $null

if ($actualRestart) {
    $releaseContract = Get-ProductionReleaseContract `
        -RequestedManifest $ReleaseManifestPath `
        -Root $resolvedRoot `
        -BackendDirectory $backendDirectory
    $projectPython = Join-Path $backendDirectory ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $projectPython -PathType Leaf)) {
        throw "Project backend virtual environment is required for a production restart."
    }
    $requiredPython = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $projectPython).Path)
    $selectedPython = [IO.Path]::GetFullPath($pythonExecutable)
    if (-not $selectedPython.Equals($requiredPython, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Production restart requires backend\.venv\Scripts\python.exe."
    }
}

if ($actualRestart) {
    $preflightOutput = @(
        Invoke-WithProcessEnvironment -Values $releaseContract.Environment -Action {
            Push-Location -LiteralPath $backendDirectory
            try {
                $output = @(& $pythonExecutable -c "import main; assert getattr(main, 'app', None) is not None; assert main.RELEASE_IDENTITY.managed; connection = main.db(); schema_version = int(connection.execute('PRAGMA user_version').fetchone()[0]); connection.close(); main.assert_release_schema_compatible(main.RELEASE_IDENTITY, schema_version)" 2>&1)
                if ($LASTEXITCODE -ne 0) {
                    throw "Production backend import preflight failed: $($output -join [Environment]::NewLine)"
                }
                $output
            } finally {
                Pop-Location
            }
        }
    )
} else {
    Push-Location -LiteralPath $backendDirectory
    try {
        $preflightOutput = @(& $pythonExecutable -c "import main; assert getattr(main, 'app', None) is not None" 2>&1)
        if ($LASTEXITCODE -ne 0) {
            throw "Backend import preflight failed: $($preflightOutput -join [Environment]::NewLine)"
        }
    } finally {
        Pop-Location
    }
}

if ($ValidateOnly) {
    Write-Host "BACKEND_RESTART_VALIDATE_OK root=$resolvedRoot python=$pythonExecutable bind=$BindAddress port=$Port"
    return
}

$expectedOldPython = if ($PreflightOnly) { $pythonExecutable } else { "" }
$existingListeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
$oldState = $null
if ($existingListeners.Count -eq 0 -and $actualRestart -and $AllowColdStart) {
    Write-Host "BACKEND_COLD_START port=$Port"
} else {
    $oldState = Get-BackendState -ExpectedPort $Port -ExpectedBind $BindAddress -ExpectedPython $expectedOldPython -RequireProxyIsolation -AllowOpaqueServiceProcess:$PreflightOnly -AllowInstalledServiceProcess:$PreflightOnly
    if (-not (Test-BackendHealth -Uri $healthUri -TimeoutSeconds $HealthProbeTimeoutSeconds)) {
        throw "Current backend failed health preflight: $healthUri"
    }
}

if ($PreflightOnly) {
    Write-Host "BACKEND_RESTART_PREFLIGHT_OK pid=$($oldState.ProcessId) launcherPid=$($oldState.RuntimeLauncherProcessId) ownership=$($oldState.RuntimeOwnership) bind=$($oldState.Address) port=$Port proxyHeadersDisabled=$($oldState.ProxyHeadersDisabled)"
    return
}

if (-not $LogDirectory.Trim()) {
    $LogDirectory = Join-Path -Path $resolvedRoot -ChildPath "logs"
}
[System.IO.Directory]::CreateDirectory($LogDirectory) | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
$stdoutLog = Join-Path -Path $LogDirectory -ChildPath "backend_restart_$timestamp.out.log"
$stderrLog = Join-Path -Path $LogDirectory -ChildPath "backend_restart_$timestamp.err.log"

if ($null -ne $oldState) {
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
}
$portDeadline = (Get-Date).AddSeconds($StopTimeoutSeconds)
while ((Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) -and (Get-Date) -lt $portDeadline) {
    Start-Sleep -Milliseconds 250
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    $priorPid = if ($null -ne $oldState) { $oldState.ProcessId } else { "none" }
    throw "Port $Port did not become free before activation; prior PID: $priorPid."
}

$newProcess = $null
$newState = $null
try {
    $newProcess = Invoke-WithProcessEnvironment -Values $releaseContract.Environment -Action {
        Start-Process `
            -FilePath $pythonExecutable `
            -ArgumentList @("-m", "uvicorn", "main:app", "--host", $BindAddress, "--port", [string]$Port, "--no-proxy-headers") `
            -WorkingDirectory $backendDirectory `
            -WindowStyle Hidden `
            -RedirectStandardOutput $stdoutLog `
            -RedirectStandardError $stderrLog `
            -PassThru
    }

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

    $newState = Get-BackendState -ExpectedPort $Port -ExpectedBind $BindAddress -ExpectedPython $pythonExecutable -RequireProxyIsolation
    if ($newState.RuntimeLauncherProcessId -ne $newProcess.Id) {
        throw "Backend runtime launcher PID $($newState.RuntimeLauncherProcessId) does not match started PID $($newProcess.Id); listener PID is $($newState.ProcessId)."
    }
    if (-not (Test-BackendReleaseIdentity -Uri $versionUri -ExpectedRelease $releaseContract.ReleaseId -ExpectedGitSha $releaseContract.GitSha -TimeoutSeconds $HealthProbeTimeoutSeconds)) {
        throw "New backend release identity does not match the selected manifest."
    }
    $activeBackendPath = Join-Path $resolvedRoot ".runtime\active-backend.json"
    $activeBackendTemp = "$activeBackendPath.tmp"
    [ordered]@{
        release_id = $releaseContract.ReleaseId
        git_sha = $releaseContract.GitSha
        release_manifest = $releaseContract.ManifestPath
        python = $pythonExecutable
        process_id = $newState.ProcessId
        launcher_process_id = $newState.RuntimeLauncherProcessId
        runtime_ownership = $newState.RuntimeOwnership
        listener_python = $newState.ExecutablePath
        activated_at = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $activeBackendTemp -Encoding UTF8
    Move-Item -LiteralPath $activeBackendTemp -Destination $activeBackendPath -Force
    $oldPid = if ($null -ne $oldState) { $oldState.ProcessId } else { "none" }
    Write-Host "BACKEND_RESTART_OK oldPid=$oldPid newPid=$($newState.ProcessId) launcherPid=$($newState.RuntimeLauncherProcessId) ownership=$($newState.RuntimeOwnership) health=200 release=$($releaseContract.ReleaseId) bind=$BindAddress port=$Port"
    Write-Host "stdout=$stdoutLog"
    Write-Host "stderr=$stderrLog"
} catch {
    $failureMessage = $_.Exception.Message
    Write-Host "BACKEND_RESTART_FAILED: $failureMessage"
    Write-LogTail -Label "stdout" -Path $stdoutLog
    Write-LogTail -Label "stderr" -Path $stderrLog
    if ($null -eq $newState -and $null -ne $newProcess) {
        try {
            $inspectedCandidate = Get-BackendState -ExpectedPort $Port -ExpectedBind $BindAddress -ExpectedPython $pythonExecutable -RequireProxyIsolation
            if ($inspectedCandidate.RuntimeLauncherProcessId -eq $newProcess.Id) {
                $newState = $inspectedCandidate
            }
        } catch {
            Write-Warning "Candidate backend ownership could not be proven during cleanup: $($_.Exception.Message)"
        }
    }
    if (
        $null -ne $newState -and
        $null -ne $newProcess -and
        $newState.RuntimeLauncherProcessId -eq $newProcess.Id -and
        $newState.ProcessId -ne $newProcess.Id
    ) {
        Stop-Process -Id $newState.ProcessId -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $newProcess -and -not $newProcess.HasExited) {
        Stop-Process -Id $newProcess.Id -Force -ErrorAction SilentlyContinue
    }
    $rollbackDeadline = (Get-Date).AddSeconds($StopTimeoutSeconds)
    while ((Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) -and (Get-Date) -lt $rollbackDeadline) {
        Start-Sleep -Milliseconds 250
    }
    if ($null -eq $oldState) {
        throw "Production cold start failed and no previous backend existed: $failureMessage"
    }
    $rollbackPython = if ($oldState.ExecutablePath -and (Test-Path -LiteralPath $oldState.ExecutablePath)) { $oldState.ExecutablePath } else { $pythonExecutable }
    $rollbackDatabase = Join-Path $backendDirectory "onenode.sqlite3"
    $rollbackEnvironment = @{
        APP_ENV = "development"
        ENV = ""
        MODE = ""
        IZO_RUNTIME_PROFILE = ""
        IZO_RELEASE_MANIFEST = ""
        APP_BUILD = "rollback-unmanaged"
        FRONTEND_BUILD_LABEL = "unknown"
        DATABASE_URL = "sqlite:///" + $rollbackDatabase.Replace("\", "/")
        DB_GUARD_ALLOWED_PATHS = $rollbackDatabase
        BOT_UPDATES_MODE = "polling"
        MAX_UPDATES_MODE = "polling"
    }
    $rollbackStdout = Join-Path -Path $LogDirectory -ChildPath "backend_rollback_$timestamp.out.log"
    $rollbackStderr = Join-Path -Path $LogDirectory -ChildPath "backend_rollback_$timestamp.err.log"
    $rollbackProcess = Invoke-WithProcessEnvironment -Values $rollbackEnvironment -Action {
        Start-Process `
            -FilePath $rollbackPython `
            -ArgumentList @("-m", "uvicorn", "main:app", "--host", $BindAddress, "--port", [string]$Port, "--no-proxy-headers") `
            -WorkingDirectory $backendDirectory `
            -WindowStyle Hidden `
            -RedirectStandardOutput $rollbackStdout `
            -RedirectStandardError $rollbackStderr `
            -PassThru
    }
    $rollbackHealthy = $false
    $rollbackDeadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    while ((Get-Date) -lt $rollbackDeadline) {
        if ($rollbackProcess.HasExited) { break }
        if (Test-BackendHealth -Uri $healthUri -TimeoutSeconds $HealthProbeTimeoutSeconds) {
            $rollbackHealthy = $true
            break
        }
        Start-Sleep -Milliseconds 500
    }
    if ($rollbackHealthy) {
        Write-Host "BACKEND_RESTART_ROLLBACK_OK pid=$($rollbackProcess.Id) health=200"
        throw "Production restart failed and legacy runtime was restored: $failureMessage"
    }
    Write-LogTail -Label "rollback stdout" -Path $rollbackStdout
    Write-LogTail -Label "rollback stderr" -Path $rollbackStderr
    throw "Production restart failed and rollback failed: $failureMessage"
}
