[CmdletBinding()]
param(
    [ValidateSet("Quick", "Full", "CI")]
    [string]$Mode = "Full",
    [string]$RepoRoot = "",
    [string]$PythonPath = "",
    [string]$NpmPath = "",
    [string]$ReceiptPath = "",
    [string]$TestHealthOutputPath = "",
    [switch]$RequireStableLiveSource,
    [switch]$StoppedBackendRecovery,
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
        [string]$WorkingDirectory,
        [string]$OutputPath = ""
    )

    Write-Host "VERIFY_STEP_START name=$Name"
    Push-Location -LiteralPath $WorkingDirectory
    try {
        if ($OutputPath.Trim()) {
            $outputDirectory = Split-Path -Parent $OutputPath
            if (-not (Test-Path -LiteralPath $outputDirectory -PathType Container)) {
                throw "Verification output directory does not exist: $outputDirectory"
            }
            $stdoutPath = $OutputPath + ".stdout"
            $stderrPath = $OutputPath + ".stderr"
            $quotePs = {
                param([string]$Value)
                return "'" + $Value.Replace("'", "''") + "'"
            }
            $quotedFile = & $quotePs $FilePath
            $quotedArguments = @($ArgumentList | ForEach-Object { & $quotePs ([string]$_) }) -join ", "
            $quotedStdout = & $quotePs $stdoutPath
            $quotedStderr = & $quotePs $stderrPath
            $captureScript = "& $quotedFile @($quotedArguments) 1> $quotedStdout 2> $quotedStderr; exit `$LASTEXITCODE"
            $encodedCapture = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($captureScript))
            $startInfo = New-Object System.Diagnostics.ProcessStartInfo
            $startInfo.FileName = "powershell.exe"
            $startInfo.Arguments = "-NoProfile -NonInteractive -EncodedCommand $encodedCapture"
            $startInfo.WorkingDirectory = $WorkingDirectory
            $startInfo.UseShellExecute = $false
            $startInfo.CreateNoWindow = $true
            $process = New-Object System.Diagnostics.Process
            $process.StartInfo = $startInfo
            [void]$process.Start()
            $process.WaitForExit()
            $stepExitCode = $process.ExitCode
            $process.Dispose()
            $capturedLines = @()
            if (Test-Path -LiteralPath $stdoutPath -PathType Leaf) {
                $capturedLines += @(Get-Content -LiteralPath $stdoutPath)
            }
            if (Test-Path -LiteralPath $stderrPath -PathType Leaf) {
                $capturedLines += @(Get-Content -LiteralPath $stderrPath)
            }
            [IO.File]::WriteAllLines($OutputPath, [string[]]$capturedLines, $utf8NoBom)
            $capturedLines | Write-Host
        } else {
            & $FilePath @ArgumentList
            $stepExitCode = $LASTEXITCODE
        }
        if ($stepExitCode -ne 0) {
            throw "Verification step '$Name' failed with exit code $stepExitCode."
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

function Get-DeterministicFrontendReleaseId {
    param([string]$Root)

    $shaOutput = @(& git.exe -C $Root rev-parse HEAD)
    if ($LASTEXITCODE -ne 0 -or $shaOutput.Count -eq 0) {
        throw "Unable to resolve the frontend verification commit."
    }
    $sha = ([string]$shaOutput[0]).Trim()
    if ($sha -notmatch "^[0-9a-f]{40}$") {
        throw "Frontend verification requires a full lowercase commit SHA."
    }
    $timestampOutput = @(& git.exe -C $Root show -s --format=%ct $sha)
    if ($LASTEXITCODE -ne 0 -or $timestampOutput.Count -eq 0) {
        throw "Unable to resolve the frontend verification commit timestamp."
    }
    [long]$commitUnix = 0
    if (-not [long]::TryParse(([string]$timestampOutput[0]).Trim(), [ref]$commitUnix) -or $commitUnix -le 0) {
        throw "Frontend verification commit timestamp is invalid."
    }
    return $sha.Substring(0, 12) + "-" +
        [DateTimeOffset]::FromUnixTimeSeconds($commitUnix).UtcDateTime.ToString("yyyyMMddHHmmss")
}

$startedAt = Get-Date
$resolvedRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$backendDirectory = Join-Path $resolvedRoot "backend"
$frontendDirectory = Join-Path $resolvedRoot "frontend"
$toolsDirectory = Join-Path $resolvedRoot "tools"
$mainFile = Join-Path $backendDirectory "main.py"
$packageFile = Join-Path $frontendDirectory "package.json"
$mapScript = Join-Path $toolsDirectory "generate_backend_map.py"
$architectureContract = Join-Path $resolvedRoot "architecture\contract.json"
$architectureInventoryScript = Join-Path $toolsDirectory "generate_architecture_inventory.py"
$contextIndexScript = Join-Path $toolsDirectory "generate_context_index.py"
$productFlowMapScript = Join-Path $toolsDirectory "generate_product_flow_map.py"
$frontendMapScript = Join-Path $toolsDirectory "generate_frontend_map.mjs"
$runtimeListenerScript = Join-Path $toolsDirectory "check-runtime-listeners.ps1"
$restartScript = Join-Path $toolsDirectory "restart-backend.ps1"
$stoppedBackendRecoveryScript = Join-Path $toolsDirectory "check-stopped-backend-recovery.ps1"
$receiptTool = Join-Path $toolsDirectory "release_verification_receipt.py"
$caddyInstallScript = Join-Path $toolsDirectory "install-caddy.ps1"
$caddyCheckScript = Join-Path $toolsDirectory "check-caddy-edge.ps1"
$testHealthPlugin = Join-Path $toolsDirectory "test_health_pytest_plugin.py"
$projectPython = Join-Path $backendDirectory ".venv\Scripts\python.exe"

foreach ($requiredPath in @(
    $mainFile,
    $packageFile,
    $mapScript,
    $architectureContract,
    $architectureInventoryScript,
    $contextIndexScript,
    $productFlowMapScript,
    $frontendMapScript,
    $runtimeListenerScript,
    $restartScript,
    $stoppedBackendRecoveryScript,
    $receiptTool,
    $caddyInstallScript,
    $caddyCheckScript,
    $testHealthPlugin
)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required verification input was not found: $requiredPath"
    }
}

$python = Resolve-Executable `
    -RequestedPath $PythonPath `
    -EnvironmentName "IZO_PYTHON_PATH" `
    -DefaultPath $projectPython `
    -CommandName "python"
$npm = Resolve-Executable `
    -RequestedPath $NpmPath `
    -EnvironmentName "IZO_NPM_PATH" `
    -DefaultPath "" `
    -CommandName "npm"
$node = Resolve-Executable `
    -RequestedPath "" `
    -EnvironmentName "IZO_NODE_PATH" `
    -DefaultPath "" `
    -CommandName "node"

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
    "tools/test_generate_architecture_inventory.py",
    "tools/test_agent_context.py",
    "tools/test_agent_symbol.py",
    "tools/test_context_docs.py",
    "tools/test_product_flows.py",
    "tools/test_supply_chain_audit.py",
    "tools/test_supply_chain_floor.py",
    "tools/test_agent_package.py",
    "tools/test_agent_sandbox.py",
    "tools/test_agent_enforce.py",
    "tools/test_frontend_release_identity.py",
    "tools/test_release_verification_receipt.py",
    "tools/test_launchers.py",
    "tools/test_repository_operation_lock.py",
    "tools/test_restart_backend_script.py",
    "tools/test_runtime_listener_contract.py",
    "tools/test_caddy_edge_contract.py",
    "tools/test_caddy_edge_integration.py",
    "tools/test_verify_script.py",
    "tools/test_backup_restore.py",
    "tools/test_ci_workflow.py",
    "tools/test_pytest_collection_contract.py",
    "tools/test_origin_isolation.py"
)
$fullTests = @("-m", "pytest", "-q", "backend", "tools")
$usesLiveChecks = $Mode -ne "CI"
$usesFullSuite = $Mode -ne "Quick"
if ($TestHealthOutputPath.Trim()) {
    if (-not $usesFullSuite) {
        throw "TestHealthOutputPath requires Full or CI verification mode."
    }
    $TestHealthOutputPath = [IO.Path]::GetFullPath($TestHealthOutputPath)
    if ([IO.Path]::GetExtension($TestHealthOutputPath) -ne ".log") {
        throw "TestHealthOutputPath must be a .log file."
    }
}
if ($StoppedBackendRecovery -and (
    $Mode -ne "Full" -or
    -not $ReceiptPath.Trim() -or
    -not $RequireStableLiveSource
)) {
    throw "StoppedBackendRecovery requires Full mode, RequireStableLiveSource and a receipt path."
}
if ($ReceiptPath.Trim() -and -not $usesFullSuite) {
    throw "Release receipts require Full or CI verification mode."
}
if ($ReceiptPath.Trim()) {
    $receiptDirectory = [IO.Path]::GetFullPath((Join-Path $resolvedRoot ".runtime\verification")).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $receiptCandidate = if ([IO.Path]::IsPathRooted($ReceiptPath)) {
        [IO.Path]::GetFullPath($ReceiptPath)
    } else {
        [IO.Path]::GetFullPath((Join-Path $resolvedRoot $ReceiptPath))
    }
    if (
        -not $receiptCandidate.StartsWith($receiptDirectory + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetExtension($receiptCandidate) -ne ".json"
    ) {
        throw "ReceiptPath must be a JSON file inside .runtime\verification."
    }
    if (-not $PlanOnly -and (Test-Path -LiteralPath $receiptCandidate)) {
        throw "Refusing to overwrite an existing release receipt."
    }
    $ReceiptPath = $receiptCandidate
}

if ($PlanOnly) {
    Write-Host "VERIFY_PLAN mode=$Mode root=$resolvedRoot"
    Write-Host "VERIFY_PLAN_STEP py_compile files=$($pythonFiles.Count)"
    Write-Host "VERIFY_PLAN_STEP backend_map_check command=python tools/generate_backend_map.py --check"
    Write-Host "VERIFY_PLAN_STEP architecture_inventory_check command=python tools/generate_architecture_inventory.py --check"
    Write-Host "VERIFY_PLAN_STEP context_index_check command=python tools/generate_context_index.py --check"
    Write-Host "VERIFY_PLAN_STEP product_flow_map_check command=python tools/generate_product_flow_map.py --check"
    Write-Host "VERIFY_PLAN_STEP frontend_map_check command=node tools/generate_frontend_map.mjs --check"
    if ($usesFullSuite) {
        Write-Host "VERIFY_PLAN_STEP caddy_runtime_integrity command=install-caddy.ps1 pinned=true"
        Write-Host "VERIFY_PLAN_STEP caddy_config_validation command=check-caddy-edge.ps1 -ConfigOnly"
    }
    if ($usesLiveChecks) {
        Write-Host "VERIFY_PLAN_STEP source_snapshot before_after=true requireStable=$RequireStableLiveSource"
        if ($StoppedBackendRecovery) {
            Write-Host "VERIFY_PLAN_STEP backend_preflight command=check-stopped-backend-recovery.ps1 -Check Backend"
            Write-Host "VERIFY_PLAN_STEP runtime_listener_contract command=check-stopped-backend-recovery.ps1 -Check Listeners"
            Write-Host "VERIFY_PLAN_STEP caddy_edge_live command=check-stopped-backend-recovery.ps1 -Check Edge"
        } else {
            Write-Host "VERIFY_PLAN_STEP backend_preflight command=restart-backend.ps1 -PreflightOnly"
            Write-Host "VERIFY_PLAN_STEP runtime_listener_contract command=check-runtime-listeners.ps1"
            Write-Host "VERIFY_PLAN_STEP caddy_edge_live command=check-caddy-edge.ps1"
        }
    }
    if ($usesFullSuite) {
        $testHealthPlan = if ($TestHealthOutputPath.Trim()) { " capture=$TestHealthOutputPath durations=10" } else { "" }
        Write-Host "VERIFY_PLAN_STEP pytest scope=backend+tools$testHealthPlan"
        Write-Host "VERIFY_PLAN_STEP frontend_lint command=npm run lint"
        Write-Host "VERIFY_PLAN_STEP frontend_build command=npm run build"
        Write-Host "VERIFY_PLAN_STEP frontend_release_identity command=npm run check:release"
        Write-Host "VERIFY_PLAN_STEP frontend_origin_isolation command=npm run check:origin"
        Write-Host "VERIFY_PLAN_STEP frontend_studio_resilience command=npm run e2e:studio-resilience"
    } else {
        Write-Host "VERIFY_PLAN_STEP pytest scope=tool-contracts"
    }
    if ($ReceiptPath.Trim()) {
        Write-Host "VERIFY_PLAN_STEP receipt=$ReceiptPath exactSha=true cleanMain=true ttlHours=4"
    }
    Write-Host "VERIFY_PLAN_OK mode=$Mode"
    return
}

# REL-LOCK-001: a Full verification is single-flight per repository. A second
# concurrent Full run must fail here, before any pytest/build/runtime work.
# CI mode runs on isolated GitHub runners and does not take the local lock.
$operationLock = $null
if ($Mode -eq "Full") {
    . (Join-Path $toolsDirectory "repository-operation-lock.ps1")
    $operationLock = Lock-IzoRepositoryOperation `
        -RepoRoot $resolvedRoot `
        -Kind "full-verify" `
        -OperationCommand "verify.ps1 -Mode $Mode"
}
try {

if ($ReceiptPath.Trim()) {
    $receiptBranch = ([string](@(& git.exe -C $resolvedRoot branch --show-current)[0])).Trim()
    if ($LASTEXITCODE -ne 0 -or $receiptBranch -ne "main") {
        throw "Release receipt verification requires branch main."
    }
    if (@(& git.exe -C $resolvedRoot status --porcelain).Count -gt 0) {
        throw "Release receipt verification requires a clean checkout."
    }
}

$beforeSnapshot = $null
if ($usesLiveChecks) {
    $beforeSnapshot = Get-SourceSnapshot -MediaDirectory (Join-Path $backendDirectory "media")
    Write-Host "VERIFY_SOURCE_BEFORE count=$($beforeSnapshot.Count) bytes=$($beforeSnapshot.Bytes) sha256=$($beforeSnapshot.Sha256)"
    # The candidate manifest is created only after this source verification. Do
    # not let a production launcher environment make the preflight require it.
    $preflightEnvironmentNames = @("IZO_RUNTIME_PROFILE", "APP_ENV", "ENV", "MODE", "IZO_RELEASE_MANIFEST")
    $preflightEnvironment = @{}
    foreach ($environmentName in $preflightEnvironmentNames) {
        $preflightEnvironment[$environmentName] = [Environment]::GetEnvironmentVariable($environmentName, "Process")
        [Environment]::SetEnvironmentVariable($environmentName, $null, "Process")
    }
    try {
        $backendPreflightArguments = if ($StoppedBackendRecovery) {
            @(
                "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", $stoppedBackendRecoveryScript,
                "-Check", "Backend", "-RepoRoot", $resolvedRoot, "-PythonPath", $python
            )
        } else {
            @(
                "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", $restartScript,
                "-PreflightOnly", "-RepoRoot", $resolvedRoot, "-PythonPath", $python
            )
        }
        Invoke-NativeStep `
            -Name "backend_preflight" `
            -FilePath "powershell.exe" `
            -ArgumentList $backendPreflightArguments `
            -WorkingDirectory $resolvedRoot
    } finally {
        foreach ($environmentName in $preflightEnvironmentNames) {
            [Environment]::SetEnvironmentVariable(
                $environmentName,
                $preflightEnvironment[$environmentName],
                "Process"
            )
        }
    }
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
if (Test-Path (Join-Path $resolvedRoot "tasks\CHAT-DEEPSEEK-001.toml")) {
    Invoke-NativeStep -Name "chat_deepseek_backend_map_generate" -FilePath $python -ArgumentList @($mapScript) -WorkingDirectory $resolvedRoot
    Invoke-NativeStep -Name "chat_deepseek_architecture_inventory_generate" -FilePath $python -ArgumentList @($architectureInventoryScript) -WorkingDirectory $resolvedRoot
    Invoke-NativeStep -Name "chat_deepseek_context_index_generate" -FilePath $python -ArgumentList @($contextIndexScript) -WorkingDirectory $resolvedRoot
    Invoke-NativeStep -Name "chat_deepseek_product_flow_generate" -FilePath $python -ArgumentList @($productFlowMapScript) -WorkingDirectory $resolvedRoot
    Invoke-NativeStep -Name "chat_deepseek_frontend_map_generate" -FilePath $node -ArgumentList @($frontendMapScript) -WorkingDirectory $resolvedRoot
    foreach ($relativeGeneratedPath in @(
        "backend/SYMBOL_MAP.md",
        "docs/generated/architecture-inventory.json",
        "docs/generated/architecture-inventory.md",
        "docs/generated/context-index.json",
        "docs/generated/context-index.md",
        "docs/generated/product-flow-map.json",
        "docs/generated/product-flow-map.md",
        "docs/generated/frontend-map.json",
        "docs/generated/frontend-map.md"
    )) {
        $generatedPath = Join-Path $resolvedRoot $relativeGeneratedPath
        $generatedBytes = [System.IO.File]::ReadAllBytes($generatedPath)
        Write-Host "CHAT_DEEPSEEK_GENERATED_BEGIN $relativeGeneratedPath"
        Write-Host ([Convert]::ToBase64String($generatedBytes))
        Write-Host "CHAT_DEEPSEEK_GENERATED_END $relativeGeneratedPath"
    }
    Write-Host "CHAT_DEEPSEEK_GENERATED_DIFF_BEGIN"
    & git -C $resolvedRoot diff --name-only
    Write-Host "CHAT_DEEPSEEK_GENERATED_DIFF_END"
}
Invoke-NativeStep -Name "backend_map_check" -FilePath $python -ArgumentList @($mapScript, "--check") -WorkingDirectory $resolvedRoot
Invoke-NativeStep -Name "architecture_inventory_check" -FilePath $python -ArgumentList @($architectureInventoryScript, "--check") -WorkingDirectory $resolvedRoot
Invoke-NativeStep -Name "context_index_check" -FilePath $python -ArgumentList @($contextIndexScript, "--check") -WorkingDirectory $resolvedRoot
Invoke-NativeStep -Name "product_flow_map_check" -FilePath $python -ArgumentList @($productFlowMapScript, "--check") -WorkingDirectory $resolvedRoot
Invoke-NativeStep -Name "frontend_map_check" -FilePath $node -ArgumentList @($frontendMapScript, "--check") -WorkingDirectory $resolvedRoot
if ($usesFullSuite) {
    Invoke-NativeStep `
        -Name "caddy_runtime_integrity" `
        -FilePath "powershell.exe" `
        -ArgumentList @(
            "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", $caddyInstallScript, "-RepoRoot", $resolvedRoot
        ) `
        -WorkingDirectory $resolvedRoot
    Invoke-NativeStep `
        -Name "caddy_config_validation" `
        -FilePath "powershell.exe" `
        -ArgumentList @(
            "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", $caddyCheckScript, "-RepoRoot", $resolvedRoot,
            "-ReleasePath", $frontendDirectory, "-ReleaseId", "verification", "-ConfigOnly"
        ) `
        -WorkingDirectory $resolvedRoot
}
if ($usesLiveChecks) {
    if ($StoppedBackendRecovery) {
        Invoke-NativeStep `
            -Name "runtime_listener_contract" `
            -FilePath "powershell.exe" `
            -ArgumentList @(
                "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", $stoppedBackendRecoveryScript,
                "-Check", "Listeners", "-RepoRoot", $resolvedRoot, "-PythonPath", $python
            ) `
            -WorkingDirectory $resolvedRoot
        Invoke-NativeStep `
            -Name "caddy_edge_live" `
            -FilePath "powershell.exe" `
            -ArgumentList @(
                "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", $stoppedBackendRecoveryScript,
                "-Check", "Edge", "-RepoRoot", $resolvedRoot, "-PythonPath", $python
            ) `
            -WorkingDirectory $resolvedRoot
    } else {
        Invoke-NativeStep `
            -Name "runtime_listener_contract" `
            -FilePath "powershell.exe" `
            -ArgumentList @(
                "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", $runtimeListenerScript,
                "-RepoRoot", $resolvedRoot,
                "-ContractPath", $architectureContract
            ) `
            -WorkingDirectory $resolvedRoot
        Invoke-NativeStep `
            -Name "caddy_edge_live" `
            -FilePath "powershell.exe" `
            -ArgumentList @(
                "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", $caddyCheckScript, "-RepoRoot", $resolvedRoot
            ) `
            -WorkingDirectory $resolvedRoot
    }
}

$testEnvironmentNames = @(
    "IZO_RUNTIME_PROFILE",
    "APP_ENV",
    "ENV",
    "MODE",
    "IZO_RELEASE_MANIFEST",
    "DATABASE_URL",
    "DB_GUARD_ALLOWED_PATHS"
)
$testEnvironment = @{}
foreach ($environmentName in $testEnvironmentNames) {
    $testEnvironment[$environmentName] = [Environment]::GetEnvironmentVariable($environmentName, "Process")
    [Environment]::SetEnvironmentVariable($environmentName, $null, "Process")
}
$previousTestHealthTelemetry = [Environment]::GetEnvironmentVariable("IZO_TEST_HEALTH_TELEMETRY", "Process")
try {
    if ($usesFullSuite) {
        $pytestArguments = if ($TestHealthOutputPath.Trim()) {
            $telemetryPath = Join-Path (Split-Path -Parent $TestHealthOutputPath) "pytest-telemetry.json"
            [Environment]::SetEnvironmentVariable("IZO_TEST_HEALTH_TELEMETRY", $telemetryPath, "Process")
            $fullTests + @("-p", "tools.test_health_pytest_plugin", "--durations=10", "--durations-min=0.1")
        } else {
            $fullTests
        }
        Invoke-NativeStep -Name "pytest_full" -FilePath $python -ArgumentList $pytestArguments -WorkingDirectory $resolvedRoot -OutputPath $TestHealthOutputPath
    } else {
        Invoke-NativeStep -Name "pytest_quick" -FilePath $python -ArgumentList $quickTests -WorkingDirectory $resolvedRoot
    }
} finally {
    [Environment]::SetEnvironmentVariable("IZO_TEST_HEALTH_TELEMETRY", $previousTestHealthTelemetry, "Process")
    foreach ($environmentName in $testEnvironmentNames) {
        [Environment]::SetEnvironmentVariable(
            $environmentName,
            $testEnvironment[$environmentName],
            "Process"
        )
    }
}

if ($usesFullSuite) {
    $previousFrontendBuildLabel = [Environment]::GetEnvironmentVariable("FRONTEND_BUILD_LABEL", "Process")
    try {
        $frontendBuildLabel = if ($previousFrontendBuildLabel -and $previousFrontendBuildLabel.Trim()) {
            $previousFrontendBuildLabel.Trim()
        } else {
            Get-DeterministicFrontendReleaseId -Root $resolvedRoot
        }
        if ($frontendBuildLabel -notmatch "^[0-9a-f]{12}-[0-9]{14}$") {
            throw "Frontend build label is not an immutable release id: $frontendBuildLabel"
        }
        [Environment]::SetEnvironmentVariable("FRONTEND_BUILD_LABEL", $frontendBuildLabel, "Process")
        Write-Host "VERIFY_FRONTEND_RELEASE release=$frontendBuildLabel"
        Invoke-NativeStep -Name "frontend_lint" -FilePath $npm -ArgumentList @("run", "lint") -WorkingDirectory $frontendDirectory
        Invoke-NativeStep -Name "frontend_build" -FilePath $npm -ArgumentList @("run", "build") -WorkingDirectory $frontendDirectory
        Invoke-NativeStep -Name "frontend_release_identity" -FilePath $npm -ArgumentList @("run", "check:release") -WorkingDirectory $frontendDirectory
        Invoke-NativeStep -Name "frontend_origin_isolation" -FilePath $npm -ArgumentList @("run", "check:origin") -WorkingDirectory $frontendDirectory
        Invoke-NativeStep -Name "frontend_studio_resilience" -FilePath $npm -ArgumentList @("run", "e2e:studio-resilience") -WorkingDirectory $frontendDirectory
    } finally {
        [Environment]::SetEnvironmentVariable("FRONTEND_BUILD_LABEL", $previousFrontendBuildLabel, "Process")
    }
}

function Get-PytestProcesses {
    $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $descendantIds = [Collections.Generic.HashSet[int]]::new()
    $pendingParents = [Collections.Generic.Queue[int]]::new()
    $pendingParents.Enqueue([int]$PID)
    while ($pendingParents.Count -gt 0) {
        $parentId = $pendingParents.Dequeue()
        foreach ($child in @($processes | Where-Object { [int]$_.ParentProcessId -eq $parentId })) {
            if ($descendantIds.Add([int]$child.ProcessId)) {
                $pendingParents.Enqueue([int]$child.ProcessId)
            }
        }
    }
    return @(
        $processes |
            Where-Object {
                $descendantIds.Contains([int]$_.ProcessId) -and
                $_.Name -match "^(?i:python(?:\.exe)?|pytest(?:\.exe)?)$" -and
                $_.CommandLine -match "(?i)(^|\s)(pytest|python(?:\.exe)?\s+-m\s+pytest)(\s|$)"
            }
    )
}

# On Windows the pytest launcher can remain visible briefly after it has
# printed the final result and returned control to PowerShell. Give normal
# process teardown a small bounded grace period before declaring a leak.
$pytestProcesses = @(Get-PytestProcesses)
for ($attempt = 0; $attempt -lt 50 -and $pytestProcesses.Count -ne 0; $attempt++) {
    Start-Sleep -Milliseconds 100
    $pytestProcesses = @(Get-PytestProcesses)
}
if ($pytestProcesses.Count -ne 0) {
    throw "Pytest processes remain after verification: $($pytestProcesses.ProcessId -join ',')"
}
if ($TestHealthOutputPath.Trim()) {
    $processLeakMarker = $TestHealthOutputPath + ".process-leak"
    [IO.File]::WriteAllText($processLeakMarker, "PASS", $utf8NoBom)
    Write-Host "VERIFY_PYTEST_PROCESS_LEAK_CHECK status=PASS"
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
    stoppedBackendRecovery = [bool]$StoppedBackendRecovery
}
if ($ReceiptPath.Trim()) {
    $summaryJson = $summary | ConvertTo-Json -Compress
    $summaryBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($summaryJson))
    $durationArgument = $duration.ToString([Globalization.CultureInfo]::InvariantCulture)
    $receiptOutput = @(
        & $python $receiptTool write `
            --root $resolvedRoot `
            --output $ReceiptPath `
            --mode $Mode `
            --started-at ($startedAt.ToUniversalTime().ToString("o")) `
            --duration-seconds $durationArgument `
            --summary-base64 $summaryBase64 2>&1
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Release verification receipt creation failed: $($receiptOutput -join [Environment]::NewLine)"
    }
    $receiptOutput | Write-Host
    Write-Host "VERIFY_RECEIPT_WRITTEN path=$ReceiptPath"
}
Write-Host "VERIFY_OK $($summary | ConvertTo-Json -Compress)"

} finally {
    if ($null -ne $operationLock) {
        Unlock-IzoRepositoryOperation -Handle $operationLock
    }
}
