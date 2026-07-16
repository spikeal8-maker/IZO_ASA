[CmdletBinding()]
param(
    [ValidateSet("Quick", "Full", "CI")]
    [string]$Mode = "Full",
    [string]$RepoRoot = "",
    [string]$PythonPath = "",
    [string]$NpmPath = "",
    [switch]$RequireStableLiveSource,
    [switch]$PlanOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

if (-not $RepoRoot.Trim()) {
    $scriptPath = [string]$MyInvocation.MyCommand.Path
    if (-not $scriptPath.Trim()) {
        throw "Verifier script path could not be resolved. Pass -RepoRoot explicitly."
    }
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $scriptPath)
}

function Resolve-Executable {
    param(
        [string]$RequestedPath,
        [string]$EnvironmentName,
        [string]$DefaultPath,
        [string]$CommandName
    )

    if ($RequestedPath.Trim()) {
        if (Test-Path -LiteralPath $RequestedPath -PathType Leaf) {
            return (Resolve-Path -LiteralPath $RequestedPath).Path
        }
        throw "Requested executable was not found: $RequestedPath"
    }
    $environmentValue = [Environment]::GetEnvironmentVariable($EnvironmentName)
    if ($environmentValue -and $environmentValue.Trim()) {
        $candidate = $environmentValue.Trim()
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
        throw "$EnvironmentName executable was not found: $candidate"
    }
    if ($DefaultPath -and (Test-Path -LiteralPath $DefaultPath -PathType Leaf)) {
        return (Resolve-Path -LiteralPath $DefaultPath).Path
    }
    $command = Get-Command $CommandName -ErrorAction SilentlyContinue
    if ($null -ne $command -and $command.Source) {
        return $command.Source
    }
    throw "Executable '$CommandName' was not found. Set the explicit path or $EnvironmentName."
}

function Invoke-NativeStep {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory
    )

    Write-Host "VERIFY_STEP_START name=$Name"
    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $FilePath @ArgumentList
        if ($LASTEXITCODE -ne 0) {
            throw "Verification step '$Name' failed with exit code $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }
    Write-Host "VERIFY_STEP_OK name=$Name"
}

function Get-SourceSnapshot {
    param([string]$MediaDirectory)

    $files = @()
    if (Test-Path -LiteralPath $MediaDirectory -PathType Container) {
        $files = @(
            Get-ChildItem -LiteralPath $MediaDirectory -File |
                Where-Object { $_.Name -like "*_source*_*.webp" } |
                Sort-Object Name
        )
    }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        [long]$totalBytes = 0
        foreach ($file in $files) {
            $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
            $totalBytes += $bytes.Length
            [void]$sha.TransformBlock($bytes, 0, $bytes.Length, $null, 0)
        }
        [void]$sha.TransformFinalBlock([byte[]]::new(0), 0, 0)
        $hash = ([BitConverter]::ToString($sha.Hash)).Replace("-", "")
    } finally {
        $sha.Dispose()
    }
    return [pscustomobject]@{
        Count = $files.Count
        Bytes = $totalBytes
        Sha256 = $hash
    }
}

function Test-SourceSnapshotEqual {
    param(
        [pscustomobject]$Before,
        [pscustomobject]$After
    )

    return $Before.Count -eq $After.Count -and $Before.Bytes -eq $After.Bytes -and $Before.Sha256 -eq $After.Sha256
}

$startedAt = Get-Date
$resolvedRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$backendDirectory = Join-Path $resolvedRoot "backend"
$frontendDirectory = Join-Path $resolvedRoot "frontend"
$toolsDirectory = Join-Path $resolvedRoot "tools"
$mainFile = Join-Path $backendDirectory "main.py"
$packageFile = Join-Path $frontendDirectory "package.json"
$mapScript = Join-Path $toolsDirectory "generate_backend_map.py"
$restartScript = Join-Path $toolsDirectory "restart-backend.ps1"

foreach ($requiredPath in @($mainFile, $packageFile, $mapScript, $restartScript)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required verification input was not found: $requiredPath"
    }
}

$python = Resolve-Executable `
    -RequestedPath $PythonPath `
    -EnvironmentName "IZO_PYTHON_PATH" `
    -DefaultPath "C:\Program Files\Python311\python.exe" `
    -CommandName "python"
$npm = Resolve-Executable `
    -RequestedPath $NpmPath `
    -EnvironmentName "IZO_NPM_PATH" `
    -DefaultPath "" `
    -CommandName "npm"

$pythonFiles = @(
    Get-ChildItem -LiteralPath $backendDirectory -Recurse -File -Filter "*.py" |
        Where-Object {
            $_.FullName -notmatch "[\\/]__pycache__[\\/]" -and
            $_.FullName -notmatch "[\\/]\.venv[\\/]"
        } |
        ForEach-Object { $_.FullName }
)
$compileBatchSize = 40
$quickTests = @(
    "-m", "pytest", "-q",
    "tools/test_generate_backend_map.py",
    "tools/test_launchers.py",
    "tools/test_restart_backend_script.py",
    "tools/test_verify_script.py",
    "tools/test_backup_restore.py",
    "tools/test_ci_workflow.py",
    "tools/test_pytest_collection_contract.py",
    "tools/test_origin_isolation.py"
)
$fullTests = @("-m", "pytest", "-q", "backend", "tools")
$usesLiveChecks = $Mode -ne "CI"
$usesFullSuite = $Mode -ne "Quick"

if ($PlanOnly) {
    Write-Host "VERIFY_PLAN mode=$Mode root=$resolvedRoot"
    Write-Host "VERIFY_PLAN_STEP py_compile files=$($pythonFiles.Count)"
    Write-Host "VERIFY_PLAN_STEP backend_map_check command=python tools/generate_backend_map.py --check"
    if ($usesLiveChecks) {
        Write-Host "VERIFY_PLAN_STEP source_snapshot before_after=true requireStable=$RequireStableLiveSource"
        Write-Host "VERIFY_PLAN_STEP backend_preflight command=restart-backend.ps1 -PreflightOnly"
    }
    if ($usesFullSuite) {
        Write-Host "VERIFY_PLAN_STEP pytest scope=backend+tools"
        Write-Host "VERIFY_PLAN_STEP frontend_lint command=npm run lint"
        Write-Host "VERIFY_PLAN_STEP frontend_build command=npm run build"
        Write-Host "VERIFY_PLAN_STEP frontend_origin_isolation command=npm run check:origin"
        Write-Host "VERIFY_PLAN_STEP frontend_studio_resilience command=npm run e2e:studio-resilience"
    } else {
        Write-Host "VERIFY_PLAN_STEP pytest scope=tool-contracts"
    }
    Write-Host "VERIFY_PLAN_OK mode=$Mode"
    return
}

$beforeSnapshot = $null
if ($usesLiveChecks) {
    $beforeSnapshot = Get-SourceSnapshot -MediaDirectory (Join-Path $backendDirectory "media")
    Write-Host "VERIFY_SOURCE_BEFORE count=$($beforeSnapshot.Count) bytes=$($beforeSnapshot.Bytes) sha256=$($beforeSnapshot.Sha256)"
    Invoke-NativeStep `
        -Name "backend_preflight" `
        -FilePath "powershell.exe" `
        -ArgumentList @(
            "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", $restartScript,
            "-PreflightOnly", "-RepoRoot", $resolvedRoot, "-PythonPath", $python
        ) `
        -WorkingDirectory $resolvedRoot
}

$compileBatchNumber = 0
for ($offset = 0; $offset -lt $pythonFiles.Count; $offset += $compileBatchSize) {
    $compileBatchNumber += 1
    $lastIndex = [Math]::Min($offset + $compileBatchSize - 1, $pythonFiles.Count - 1)
    $compileBatch = @($pythonFiles[$offset..$lastIndex])
    $compileArguments = @("-m", "py_compile") + $compileBatch
    Invoke-NativeStep `
        -Name "py_compile_$compileBatchNumber" `
        -FilePath $python `
        -ArgumentList $compileArguments `
        -WorkingDirectory $resolvedRoot
}
Invoke-NativeStep -Name "backend_map_check" -FilePath $python -ArgumentList @($mapScript, "--check") -WorkingDirectory $resolvedRoot

if ($usesFullSuite) {
    Invoke-NativeStep -Name "pytest_full" -FilePath $python -ArgumentList $fullTests -WorkingDirectory $resolvedRoot
    Invoke-NativeStep -Name "frontend_lint" -FilePath $npm -ArgumentList @("run", "lint") -WorkingDirectory $frontendDirectory
    Invoke-NativeStep -Name "frontend_build" -FilePath $npm -ArgumentList @("run", "build") -WorkingDirectory $frontendDirectory
    Invoke-NativeStep -Name "frontend_origin_isolation" -FilePath $npm -ArgumentList @("run", "check:origin") -WorkingDirectory $frontendDirectory
    Invoke-NativeStep -Name "frontend_studio_resilience" -FilePath $npm -ArgumentList @("run", "e2e:studio-resilience") -WorkingDirectory $frontendDirectory
} else {
    Invoke-NativeStep -Name "pytest_quick" -FilePath $python -ArgumentList $quickTests -WorkingDirectory $resolvedRoot
}

$pytestProcesses = @(
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -match "^(?i:python(?:\.exe)?|pytest(?:\.exe)?)$" -and
            $_.CommandLine -match "(?i)(^|\s)(pytest|python(?:\.exe)?\s+-m\s+pytest)(\s|$)"
        }
)
if ($pytestProcesses.Count -ne 0) {
    throw "Pytest processes remain after verification: $($pytestProcesses.ProcessId -join ',')"
}

$afterSnapshot = $null
$sourceStable = $null
if ($usesLiveChecks) {
    $afterSnapshot = Get-SourceSnapshot -MediaDirectory (Join-Path $backendDirectory "media")
    $sourceStable = Test-SourceSnapshotEqual -Before $beforeSnapshot -After $afterSnapshot
    if (-not $sourceStable) {
        $beforeJson = $beforeSnapshot | ConvertTo-Json -Compress
        $afterJson = $afterSnapshot | ConvertTo-Json -Compress
        Write-Host "VERIFY_SOURCE_CONCURRENT_CHANGE before=$beforeJson after=$afterJson"
        if ($RequireStableLiveSource) {
            throw "Live source snapshot changed during strict maintenance verification."
        }
        Write-Warning "Live source changed while production remained online. Tests use isolated temp roots; rerun with -RequireStableLiveSource only in a maintenance window."
    }
    Write-Host "VERIFY_SOURCE_AFTER count=$($afterSnapshot.Count) bytes=$($afterSnapshot.Bytes) sha256=$($afterSnapshot.Sha256)"
}

$duration = [math]::Round(((Get-Date) - $startedAt).TotalSeconds, 2)
$summary = [ordered]@{
    ok = $true
    mode = $Mode
    durationSeconds = $duration
    pythonFiles = $pythonFiles.Count
    fullSuite = $usesFullSuite
    liveChecks = $usesLiveChecks
    sourceCount = if ($null -ne $afterSnapshot) { $afterSnapshot.Count } else { $null }
    sourceBytes = if ($null -ne $afterSnapshot) { $afterSnapshot.Bytes } else { $null }
    sourceSha256 = if ($null -ne $afterSnapshot) { $afterSnapshot.Sha256 } else { $null }
    sourceStable = $sourceStable
}
Write-Host "VERIFY_OK $($summary | ConvertTo-Json -Compress)"
