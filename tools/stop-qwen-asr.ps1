param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [int]$Port = 8001
)

$ErrorActionPreference = "Stop"
$pidFile = Join-Path $RepoRoot ".tools\qwen-asr.pid"
$wrapperPidFile = Join-Path $RepoRoot ".tools\qwen-asr-wrapper.pid"
$pids = @()
foreach ($savedPidFile in @($pidFile, $wrapperPidFile)) {
    if (Test-Path -LiteralPath $savedPidFile) {
        $savedPid = Get-Content -LiteralPath $savedPidFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($savedPid -match "^\d+$") { $pids += [int]$savedPid }
    }
}
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) { $pids += $listener.OwningProcess }

foreach ($processId in ($pids | Sort-Object -Unique)) {
    Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $wrapperPidFile -Force -ErrorAction SilentlyContinue
Write-Output "QWEN_ASR_STOPPED port=$Port"
