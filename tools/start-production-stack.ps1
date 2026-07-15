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
    $line | Tee-Object -FilePath $logPath -Append
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
        throw "$Name executable is missing: $FilePath"
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
    $launcher = Join-Path $repoRoot "start-public-autostart.bat"
    Write-StackLog "Starting public backend and frontend via $launcher"
    $launch = Start-Process -FilePath "cmd.exe" -ArgumentList @("/d", "/c", "`"$launcher`"") -WorkingDirectory $repoRoot -WindowStyle Hidden -Wait -PassThru
    Write-StackLog "Public launcher finished with exit code $($launch.ExitCode)."
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
