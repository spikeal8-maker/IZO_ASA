param(
    [switch]$CheckOnly,
    [int]$StartupTimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $repoRoot "logs"
$ollamaExe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
$comfyRoot = "C:\LLM\ComfyUI_windows_portable_nvidia_cu126\ComfyUI_windows_portable"
$comfyBat = Join-Path $comfyRoot "run_nvidia_gpu.bat"
$frpExe = "C:\frp\frpc.exe"
$frpConfig = "C:\frp\frpc.toml"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir ("production-autostart_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

function Write-StackLog {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $logPath -Value $line
    Write-Host $line
}

function Test-HttpEndpoint {
    param([string]$Uri)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 5
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
    } catch {
        return $false
    }
}

function Wait-HttpEndpoint {
    param(
        [string]$Name,
        [string]$Uri,
        [int]$TimeoutSeconds
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (Test-HttpEndpoint -Uri $Uri) {
            Write-StackLog "$Name ready: $Uri"
            return $true
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    Write-StackLog "$Name FAILED health check: $Uri"
    return $false
}

function Start-HiddenProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory
    )
    if (-not (Test-Path -LiteralPath $FilePath)) {
        $resolvedCommand = Get-Command $FilePath -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if (-not $resolvedCommand) {
            throw "$Name executable is missing: $FilePath"
        }
        $FilePath = $resolvedCommand.Source
    }
    $params = @{
        FilePath = $FilePath
        ArgumentList = $ArgumentList
        WindowStyle = "Hidden"
        PassThru = $true
    }
    if ($WorkingDirectory) {
        $params.WorkingDirectory = $WorkingDirectory
    }
    $process = Start-Process @params
    Write-StackLog "$Name started, pid=$($process.Id)"
}

function Start-BootstrapBackend {
    $backendDir = Join-Path $repoRoot "backend"
    $databasePath = Join-Path $backendDir "onenode.sqlite3"
    $backendLog = Join-Path $logDir ("bootstrap_backend_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
    $databaseUrl = "sqlite:///" + $databasePath.Replace("\", "/")
    $serverCommand = @"
`$env:APP_ENV='production'
`$env:DATABASE_URL='$databaseUrl'
`$env:DB_GUARD_ALLOWED_PATHS='$databasePath'
`$env:DB_GUARD_MIN_SIZE_MB='10'
`$env:DB_GUARD_MIN_USERS='5'
`$env:DB_GUARD_MIN_ACTIVE_ADMINS='1'
`$env:TRUSTED_COOKIE_SECURE='true'
`$env:TRUSTED_COOKIE_SAMESITE='none'
`$env:TRUSTED_COOKIE_PATH='/'
`$env:TRUST_CLOUDFLARE_HEADERS='true'
`$env:MAX_API_BASE_URL='https://platform-api2.max.ru'
`$env:BOT_UPDATES_MODE='polling'
`$env:MAX_UPDATES_MODE='polling'
Set-Location -LiteralPath '$backendDir'
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --no-proxy-headers *>> '$backendLog'
"@
    $encodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($serverCommand))
    Start-HiddenProcess -Name "Bootstrap backend" -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-NonInteractive", "-EncodedCommand", $encodedCommand) `
        -WorkingDirectory $repoRoot
    Write-StackLog "Bootstrap backend log: $backendLog"
    if (-not (Wait-HttpEndpoint -Name "Bootstrap backend" -Uri "http://127.0.0.1:8000/api/health" -TimeoutSeconds 90)) {
        throw "Bootstrap backend did not start. See $backendLog"
    }
}

Write-StackLog "Production stack check started. user=$env:USERNAME computer=$env:COMPUTERNAME checkOnly=$CheckOnly"

$components = @(
    @{ Name = "Ollama"; Uri = "http://127.0.0.1:11434/api/tags" },
    @{ Name = "Config UI"; Uri = "http://127.0.0.1:8188/system_stats" },
    @{ Name = "Backend"; Uri = "http://127.0.0.1:8000/api/health" },
    @{ Name = "Frontend"; Uri = "http://127.0.0.1:5173/" }
)

if ($CheckOnly) {
    $failed = @()
    foreach ($component in $components) {
        $ok = Test-HttpEndpoint -Uri $component.Uri
        Write-StackLog "$($component.Name): $(if ($ok) { 'ready' } else { 'offline' })"
        if (-not $ok) { $failed += $component.Name }
    }
    $frp = Get-CimInstance Win32_Process -Filter "Name='frpc.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*$frpConfig*" }
    Write-StackLog "FRP: $(if ($frp) { 'running' } else { 'offline' })"
    if (-not $frp) { $failed += "FRP" }
    $publicOk = Test-HttpEndpoint -Uri "https://izo.alikinas.ru/api/health"
    Write-StackLog "Public endpoint: $(if ($publicOk) { 'ready' } else { 'offline' })"
    if (-not $publicOk) { $failed += "Public endpoint" }
    if ($failed.Count -gt 0) {
        throw "Production stack is not ready: $($failed -join ', ')"
    }
    Write-StackLog "Production stack check passed."
    exit 0
}

if (-not (Test-HttpEndpoint -Uri "http://127.0.0.1:11434/api/tags")) {
    Start-HiddenProcess -Name "Ollama" -FilePath $ollamaExe -ArgumentList @("serve") -WorkingDirectory (Split-Path -Parent $ollamaExe)
    if (-not (Wait-HttpEndpoint -Name "Ollama" -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSeconds 60)) {
        throw "Ollama did not start."
    }
} else {
    Write-StackLog "Ollama already ready."
}

if (-not (Test-HttpEndpoint -Uri "http://127.0.0.1:8188/system_stats")) {
    Start-HiddenProcess -Name "Config UI" -FilePath "cmd.exe" -ArgumentList @("/d", "/c", "`"$comfyBat`"") -WorkingDirectory $comfyRoot
    if (-not (Wait-HttpEndpoint -Name "Config UI" -Uri "http://127.0.0.1:8188/system_stats" -TimeoutSeconds $StartupTimeoutSeconds)) {
        throw "Config UI did not start."
    }
} else {
    Write-StackLog "Config UI already ready."
}

$frp = Get-CimInstance Win32_Process -Filter "Name='frpc.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*$frpConfig*" }
if (-not $frp) {
    Start-HiddenProcess -Name "FRP" -FilePath $frpExe -ArgumentList @("-c", $frpConfig) -WorkingDirectory (Split-Path -Parent $frpExe)
    Start-Sleep -Seconds 3
} else {
    Write-StackLog "FRP already running."
}

$backendReady = Test-HttpEndpoint -Uri "http://127.0.0.1:8000/api/health"
$frontendReady = Test-HttpEndpoint -Uri "http://127.0.0.1:5173/"
if (-not ($backendReady -and $frontendReady)) {
    # Candidate browser smoke checks API-backed routes. On a cold boot the
    # backend must therefore be available before start-public publishes the
    # release; the public launcher replaces this bootstrap process afterward.
    if (-not $backendReady) {
        Start-BootstrapBackend
    }
    $launcher = Join-Path $repoRoot "start-public-autostart.bat"
    Write-StackLog "Starting public backend and frontend via $launcher"
    $launch = Start-Process -FilePath "cmd.exe" -ArgumentList @("/d", "/c", "`"$launcher`"") -WorkingDirectory $repoRoot -WindowStyle Hidden -Wait -PassThru
    Write-StackLog "Public launcher finished with exit code $($launch.ExitCode)."
    if ($launch.ExitCode -ne 0) {
        throw "Public launcher failed with exit code $($launch.ExitCode)."
    }
} else {
    Write-StackLog "Backend and frontend already ready."
}

$failed = @()
foreach ($component in $components) {
    if (-not (Wait-HttpEndpoint -Name $component.Name -Uri $component.Uri -TimeoutSeconds 60)) {
        $failed += $component.Name
    }
}
if (-not (Get-CimInstance Win32_Process -Filter "Name='frpc.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*$frpConfig*" })) {
    $failed += "FRP"
}
if (-not (Wait-HttpEndpoint -Name "Public endpoint" -Uri "https://izo.alikinas.ru/api/health" -TimeoutSeconds 60)) {
    $failed += "Public endpoint"
}

if ($failed.Count -gt 0) {
    throw "Autostart completed with failed components: $($failed -join ', '). Log: $logPath"
}

Write-StackLog "Production stack is ready. Qwen ASR remains intentionally stopped to protect the shared generation GPU."
