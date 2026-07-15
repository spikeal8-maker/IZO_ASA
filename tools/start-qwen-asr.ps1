param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$Model = "Qwen/Qwen3-ASR-1.7B",
    [string]$ModelRevision = "7278e1e70fe206f11671096ffdd38061171dd6e5",
    [int]$Port = 8001
)

$ErrorActionPreference = "Stop"
$runtime = Join-Path $RepoRoot ".tools\qwen-asr-venv"
$asciiRuntime = "C:\izo-qwen-asr"
$venvPython = Join-Path $asciiRuntime "Scripts\python.exe"
$pidFile = Join-Path $RepoRoot ".tools\qwen-asr.pid"
$wrapperPidFile = Join-Path $RepoRoot ".tools\qwen-asr-wrapper.pid"
$logDir = Join-Path $RepoRoot "logs"

if (-not (Test-Path -LiteralPath (Join-Path $runtime "Scripts\python.exe"))) {
    throw "Qwen ASR environment is missing: $runtime"
}
if (-not (Test-Path -LiteralPath $asciiRuntime)) {
    New-Item -ItemType Junction -Path $asciiRuntime -Target $runtime | Out-Null
}
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Qwen ASR Python is missing: $venvPython"
}
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    Write-Output "QWEN_ASR_ALREADY_RUNNING pid=$($listener[0].OwningProcess) port=$Port"
    exit 0
}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stdout = Join-Path $logDir "qwen-asr.out.log"
$stderr = Join-Path $logDir "qwen-asr.err.log"
$oldModel = $env:QWEN_ASR_MODEL
$oldModelRevision = $env:QWEN_ASR_MODEL_REVISION
$oldHfHome = $env:HF_HOME
$oldSymlinkWarning = $env:HF_HUB_DISABLE_SYMLINKS_WARNING
try {
    $env:QWEN_ASR_MODEL = $Model
    $env:QWEN_ASR_MODEL_REVISION = $ModelRevision
    $env:HF_HOME = "C:\izo-qwen-cache"
    $env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
    # Keep a PowerShell parent alive because the Windows venv launcher creates
    # the real Python server as a child process and then exits.
    $escapedPython = $venvPython.Replace("'", "''")
    $escapedRepoRoot = $RepoRoot.Replace("'", "''")
    $serverCommand = "Set-Location -LiteralPath '$escapedRepoRoot'; & '$escapedPython' -m uvicorn tools.qwen_asr_service:app --host 127.0.0.1 --port $Port"
    $encodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($serverCommand))
    $wrapper = Start-Process -FilePath "powershell.exe" `
        -ArgumentList "-NoProfile -NonInteractive -EncodedCommand $encodedCommand" `
        -WorkingDirectory $RepoRoot `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -LiteralPath $wrapperPidFile -Value $wrapper.Id -Encoding ascii
    Write-Output "QWEN_ASR_STARTING wrapper_pid=$($wrapper.Id) port=$Port model=$Model"
    Write-Output "QWEN_ASR_LOG stdout=$stdout stderr=$stderr"

    $deadline = (Get-Date).AddSeconds(90)
    do {
        if ($wrapper.HasExited) {
            throw "Qwen ASR stopped during startup. See $stderr"
        }
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
            if ($health.ok) {
                $activeListener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1
                Set-Content -LiteralPath $pidFile -Value $activeListener.OwningProcess -Encoding ascii
                Write-Output "QWEN_ASR_READY pid=$($activeListener.OwningProcess) port=$Port device=$($health.device)"
                exit 0
            }
        } catch {
            Start-Sleep -Seconds 1
        }
    } while ((Get-Date) -lt $deadline)
    throw "Qwen ASR did not become ready within 90 seconds. See $stderr"
} finally {
    $env:QWEN_ASR_MODEL = $oldModel
    $env:QWEN_ASR_MODEL_REVISION = $oldModelRevision
    $env:HF_HOME = $oldHfHome
    $env:HF_HUB_DISABLE_SYMLINKS_WARNING = $oldSymlinkWarning
}
