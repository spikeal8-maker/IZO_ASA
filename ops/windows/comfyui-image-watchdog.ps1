param(
    [string]$RequestPath = 'C:\IZO_ASA\runtime\comfyui-watchdog\request.json',
    [string]$HealthPath = 'C:\IZO_ASA\health\comfyui-watchdog-current.json',
    [string]$ServiceName = 'IZOComfyUI'
)

$ErrorActionPreference = 'Stop'
$runtimeRoot = [System.IO.Path]::GetFullPath('C:\IZO_ASA\runtime\comfyui-watchdog')
$resolvedRequest = [System.IO.Path]::GetFullPath($RequestPath)
if (-not $resolvedRequest.StartsWith($runtimeRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'The watchdog request must stay inside the fixed IZO_ASA runtime directory.'
}

$lockPath = Join-Path $runtimeRoot 'watchdog.lock'
$lock = $null
try {
    New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
    try {
        $lock = [System.IO.File]::Open(
            $lockPath,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None
        )
    } catch [System.IO.IOException] {
        exit 0
    }
    if (-not (Test-Path -LiteralPath $resolvedRequest -PathType Leaf)) {
        exit 0
    }

    $request = Get-Content -LiteralPath $resolvedRequest -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($request.SchemaVersion -ne 1 -or $request.Source -ne 'image-generation-watchdog') {
        throw 'Invalid ComfyUI watchdog request schema.'
    }
    $requestedAt = [DateTimeOffset]::Parse([string]$request.RequestedAt)
    $age = [DateTimeOffset]::UtcNow - $requestedAt.ToUniversalTime()
    if ($age.TotalSeconds -lt -30 -or $age.TotalMinutes -gt 15) {
        throw 'Stale or future ComfyUI watchdog request.'
    }

    Restart-Service -Name $ServiceName -Force
    $deadline = (Get-Date).AddSeconds(120)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
        if ($service -and $service.Status -eq 'Running') {
            try {
                $response = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8188/object_info' -TimeoutSec 5
                if ($response.StatusCode -eq 200) {
                    $ready = $true
                    break
                }
            } catch {
            }
        }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) {
        throw 'ComfyUI did not become healthy after the hard restart.'
    }

    $receipt = [ordered]@{
        SchemaVersion = 1
        Timestamp = [DateTimeOffset]::UtcNow.ToString('o')
        Status = 'RECOVERED'
        RequestId = [string]$request.RequestId
        JobId = [string]$request.JobId
        Service = $ServiceName
        EndpointReady = $true
    }
    $healthDirectory = Split-Path -Parent $HealthPath
    New-Item -ItemType Directory -Path $healthDirectory -Force | Out-Null
    $temporary = "$HealthPath.$PID.tmp"
    $receipt | ConvertTo-Json | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $HealthPath -Force
    Remove-Item -LiteralPath $resolvedRequest -Force
} catch {
    $failure = [ordered]@{
        SchemaVersion = 1
        Timestamp = [DateTimeOffset]::UtcNow.ToString('o')
        Status = 'ERROR'
        Error = $_.Exception.Message
        Service = $ServiceName
    }
    $healthDirectory = Split-Path -Parent $HealthPath
    New-Item -ItemType Directory -Path $healthDirectory -Force | Out-Null
    $failure | ConvertTo-Json | Set-Content -LiteralPath $HealthPath -Encoding UTF8
    exit 1
} finally {
    if ($lock) {
        $lock.Dispose()
    }
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
}
