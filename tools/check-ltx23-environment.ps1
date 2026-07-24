[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ComfyRoot,
    [string]$ManifestPath = "",
    [string]$WorkflowPath = "",
    [switch]$SkipHashes,
    [switch]$SkipCommits,
    [switch]$SkipRuntime,
    [switch]$CheckEndpoint,
    [string]$ComfyUrl = "http://127.0.0.1:8188"
)

$ErrorActionPreference = "Stop"
$failures = New-Object System.Collections.Generic.List[string]
if (-not $ManifestPath) {
    $ManifestPath = Join-Path $PSScriptRoot "..\ops\ltx23\runtime-manifest.json"
}
if (-not $WorkflowPath) {
    $WorkflowPath = Join-Path $PSScriptRoot "..\backend\workflows\ltx23_t2v_api.json"
}

function Add-Check {
    param([bool]$Passed, [string]$Message)
    if ($Passed) {
        Write-Host "OK  $Message"
    } else {
        Write-Host "ERR $Message" -ForegroundColor Red
        $script:failures.Add($Message)
    }
}

$manifestFile = Resolve-Path -LiteralPath $ManifestPath -ErrorAction Stop
$manifest = Get-Content -LiteralPath $manifestFile -Raw | ConvertFrom-Json
$comfy = Resolve-Path -LiteralPath $ComfyRoot -ErrorAction Stop

foreach ($model in $manifest.required_models) {
    $relativePath = [string]$model.path
    $file = Join-Path $comfy ($relativePath -replace "/", "\")
    $exists = Test-Path -LiteralPath $file -PathType Leaf
    Add-Check $exists "model $relativePath exists"
    if (-not $exists) { continue }

    $item = Get-Item -LiteralPath $file
    Add-Check ($item.Length -eq [int64]$model.bytes) "model $relativePath size"
    if (-not $SkipHashes) {
        $actualHash = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToUpperInvariant()
        Add-Check ($actualHash -eq ([string]$model.sha256).ToUpperInvariant()) "model $relativePath SHA256"
    }
}

$gitCandidates = @(
    (Get-Command git -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
    "C:\Program Files\Git\bin\git.exe"
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
if (-not $gitCandidates) {
    $desktopGit = Get-ChildItem `
        -Path "C:\Users\$env:USERNAME\AppData\Local\GitHubDesktop\app-*\resources\app\git\cmd\git.exe" `
        -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending |
        Select-Object -First 1 -ExpandProperty FullName
    if ($desktopGit) { $gitCandidates = @($desktopGit) }
}
$gitExe = $gitCandidates | Select-Object -First 1

if ($SkipCommits) {
    Write-Host "SKIP git commit checks"
} elseif ($gitExe) {
    $comfyCommit = (& $gitExe -C $comfy rev-parse HEAD 2>$null).Trim()
    Add-Check ($comfyCommit -eq [string]$manifest.runtime.comfyui_commit) "ComfyUI commit"
    foreach ($node in $manifest.custom_nodes) {
        $nodePath = Join-Path $comfy ("custom_nodes\" + [string]$node.directory)
        $exists = Test-Path -LiteralPath $nodePath -PathType Container
        Add-Check $exists "custom node $($node.directory) exists"
        if (-not $exists) { continue }
        $actualCommit = (& $gitExe -C $nodePath rev-parse HEAD 2>$null).Trim()
        Add-Check ($actualCommit -eq [string]$node.commit) "custom node $($node.directory) commit"
    }
} else {
    Add-Check $false "git executable available for custom-node commit checks"
}

$workflowExists = Test-Path -LiteralPath $WorkflowPath -PathType Leaf
Add-Check $workflowExists "server-owned API workflow exists"
if ($workflowExists) {
    try {
        $workflowText = Get-Content -LiteralPath $WorkflowPath -Raw
        $workflow = $workflowText | ConvertFrom-Json
        $nodes = @()
        if ($workflow.PSObject.Properties.Count -gt 0) {
            $nodes = @($workflow.PSObject.Properties.Value | Where-Object { $_.class_type })
        }
        if ($nodes.Count -eq 0 -and $workflow.extra -and $workflow.extra.prompt) {
            $nodes = @($workflow.extra.prompt.PSObject.Properties.Value | Where-Object { $_.class_type })
        }
        Add-Check ($nodes.Count -gt 0) "workflow is ComfyUI API format"
        foreach ($classType in $manifest.workflow.required_class_types) {
            Add-Check (@($nodes | Where-Object { $_.class_type -eq $classType }).Count -gt 0) "workflow contains $classType"
        }
        $textNodeCount = @($nodes | Where-Object { $_.class_type -eq "CLIPTextEncode" }).Count
        Add-Check ($textNodeCount -ge [int]$manifest.workflow.required_text_nodes) "workflow has positive and negative text nodes"
        foreach ($forbidden in $manifest.workflow.forbidden_references) {
            Add-Check (-not $workflowText.Contains([string]$forbidden)) "workflow excludes stale reference $forbidden"
        }
    } catch {
        Add-Check $false "workflow JSON parses: $($_.Exception.Message)"
    }
}

$python = Join-Path (Split-Path -Parent $comfy) "python_embeded\python.exe"
if (-not $SkipRuntime) {
    Add-Check (Test-Path -LiteralPath $python -PathType Leaf) "portable Python exists"
    if (Test-Path -LiteralPath $python -PathType Leaf) {
        $runtime = & $python -c "import json,sys,torch; print(json.dumps({'python':sys.version.split()[0],'torch':torch.__version__,'cuda':torch.version.cuda,'cuda_available':torch.cuda.is_available()}))"
        try {
            $runtimeInfo = $runtime | ConvertFrom-Json
            Add-Check ($runtimeInfo.python -eq [string]$manifest.runtime.python) "Python version $($runtimeInfo.python)"
            Add-Check ($runtimeInfo.torch -eq [string]$manifest.runtime.torch) "Torch version $($runtimeInfo.torch)"
            Add-Check ($runtimeInfo.cuda -eq [string]$manifest.runtime.cuda_runtime) "Torch CUDA runtime $($runtimeInfo.cuda)"
            Add-Check ([bool]$runtimeInfo.cuda_available) "CUDA device is available to Torch"
        } catch {
            Add-Check $false "portable Python runtime report parses"
        }
    }
}

if ($CheckEndpoint) {
    try {
        $stats = Invoke-RestMethod -Uri ($ComfyUrl.TrimEnd("/") + "/system_stats") -TimeoutSec 10
        $devices = @($stats.devices)
        Add-Check ($devices.Count -gt 0) "ComfyUI reports at least one device"
        Add-Check (@($devices | Where-Object { ([string]$_.type) -notmatch "cpu" }).Count -gt 0) "ComfyUI reports a non-CPU device"
    } catch {
        Add-Check $false "ComfyUI /system_stats is reachable"
    }
}

if ($failures.Count -gt 0) {
    Write-Host "LTX23_PREFLIGHT_FAILED count=$($failures.Count)" -ForegroundColor Red
    exit 1
}

Write-Host "LTX23_PREFLIGHT_OK"
exit 0
