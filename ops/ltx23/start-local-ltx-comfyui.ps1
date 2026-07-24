param(
    [string]$ComfyRoot = "F:\AI\ComfyUI\ComfyUI_windows_portable\ComfyUI",
    [string]$PythonPath = "F:\AI\ComfyUI\ComfyUI_windows_portable\python_embeded\python.exe",
    [string]$GpuUuid = "GPU-35731bea-a468-e491-1627-5fa90aff0535",
    [int]$Port = 8190,
    [double]$ReserveVramGb = 1.0,
    [string]$StateDirectory = "F:\AI\ComfyUI\LTX23_user",
    [int]$RestartDelaySeconds = 2
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $ComfyRoot -PathType Container)) {
    throw "ComfyUI root not found: $ComfyRoot"
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Portable Python not found: $PythonPath"
}

New-Item -ItemType Directory -Path $StateDirectory -Force | Out-Null
$env:CUDA_VISIBLE_DEVICES = $GpuUuid
$env:PYTHONUTF8 = "1"

$arguments = @(
    "-s",
    (Join-Path $ComfyRoot "main.py"),
    "--windows-standalone-build",
    "--listen", "127.0.0.1",
    "--port", "$Port",
    "--disable-auto-launch",
    "--lowvram",
    "--reserve-vram", "$ReserveVramGb",
    "--user-directory", $StateDirectory,
    "--database-url", "sqlite:///$($StateDirectory.Replace('\', '/'))/comfyui.db",
    "--disable-all-custom-nodes",
    "--whitelist-custom-nodes",
    "ComfyUI-GGUF",
    "ComfyUI-KJNodes",
    "ComfyUI-LTXVideo",
    "ComfyUI-VideoHelperSuite"
)

while ($true) {
    & $PythonPath @arguments
    $exitCode = $LASTEXITCODE
    Write-Warning "LTX ComfyUI exited with code $exitCode; restarting in $RestartDelaySeconds seconds."
    Start-Sleep -Seconds $RestartDelaySeconds
}
