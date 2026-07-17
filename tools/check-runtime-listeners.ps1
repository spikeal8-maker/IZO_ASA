[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$ContractPath = "",
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
        throw "Runtime listener checker path could not be resolved. Pass -RepoRoot explicitly."
    }
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $scriptPath)
}

$resolvedRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
if (-not $ContractPath.Trim()) {
    $ContractPath = Join-Path $resolvedRoot "architecture\contract.json"
} elseif (-not [System.IO.Path]::IsPathRooted($ContractPath)) {
    $ContractPath = Join-Path $resolvedRoot $ContractPath
}
if (-not (Test-Path -LiteralPath $ContractPath -PathType Leaf)) {
    throw "Architecture contract was not found: $ContractPath"
}

function Get-OptionalProperty {
    param(
        [object]$InputObject,
        [string]$Name,
        [object]$DefaultValue
    )

    $property = $InputObject.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $DefaultValue
    }
    return $property.Value
}

function Test-ContainsAllInsensitive {
    param(
        [string]$Text,
        [object[]]$Fragments
    )

    foreach ($fragmentValue in @($Fragments)) {
        $fragment = [string]$fragmentValue
        if ($Text.IndexOf($fragment, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
            return $false
        }
    }
    return $true
}

$contract = Get-Content -LiteralPath $ContractPath -Raw -Encoding UTF8 | ConvertFrom-Json
$listeners = @($contract.listeners | Sort-Object { [int]$_.port })
if ($listeners.Count -eq 0) {
    throw "Architecture contract contains no listener registrations."
}

$listenerById = @{}
$registeredPorts = @{}
foreach ($listenerConfig in $listeners) {
    $listenerId = [string]$listenerConfig.id
    $port = [int]$listenerConfig.port
    if ($listenerById.ContainsKey($listenerId)) {
        throw "Duplicate listener id in architecture contract: $listenerId"
    }
    if ($registeredPorts.ContainsKey($port)) {
        throw "Duplicate listener port in architecture contract: $port"
    }
    $listenerById[$listenerId] = $listenerConfig
    $registeredPorts[$port] = $listenerId
}

$runtimeGuards = $contract.runtime_guards
$fullAppProcessNames = @($runtimeGuards.full_app_process_names)
$fullAppSignature = @($runtimeGuards.full_app_command_contains)
if ($fullAppProcessNames.Count -eq 0) {
    throw "Architecture contract contains no full-app process-name allowlist."
}
if ($fullAppSignature.Count -eq 0) {
    throw "Architecture contract contains no full-app process signature."
}
$allowedFullAppPorts = @{}
foreach ($listenerIdValue in @($runtimeGuards.allowed_full_app_listener_ids)) {
    $listenerId = [string]$listenerIdValue
    if (-not $listenerById.ContainsKey($listenerId)) {
        throw "Full-app guard references unknown listener id: $listenerId"
    }
    $allowedFullAppPorts[[int]$listenerById[$listenerId].port] = $listenerId
}
if ($allowedFullAppPorts.Count -eq 0) {
    throw "Architecture contract allows no listener for the full application."
}

if ($PlanOnly) {
    Write-Host "RUNTIME_LISTENER_PLAN root=$resolvedRoot contract=$ContractPath"
    foreach ($listenerConfig in $listeners) {
        $required = [bool]$listenerConfig.required_local
        $processNames = @($listenerConfig.process_names) -join ","
        $commandContains = @($listenerConfig.command_contains) -join ","
        $bindEnforcement = [string](Get-OptionalProperty -InputObject $listenerConfig -Name "bind_enforcement" -DefaultValue "error")
        Write-Host "RUNTIME_LISTENER_PLAN_ROLE id=$($listenerConfig.id) bind=$($listenerConfig.bind) port=$($listenerConfig.port) required=$required bindEnforcement=$bindEnforcement process=$processNames command=$commandContains"
    }
    Write-Host "RUNTIME_LISTENER_PLAN_FULL_APP process=$($fullAppProcessNames -join ',') allowedPorts=$((@($allowedFullAppPorts.Keys) | Sort-Object) -join ',') signature=$($fullAppSignature -join ',')"
    Write-Host "RUNTIME_LISTENER_PLAN_OK roles=$($listeners.Count)"
    return
}

$errors = New-Object System.Collections.Generic.List[string]
[int]$warningCount = 0
[int]$presentCount = 0
[int]$absentCount = 0

foreach ($listenerConfig in $listeners) {
    $listenerId = [string]$listenerConfig.id
    $expectedBind = [string]$listenerConfig.bind
    $port = [int]$listenerConfig.port
    $required = [bool]$listenerConfig.required_local
    $bindEnforcement = [string](Get-OptionalProperty -InputObject $listenerConfig -Name "bind_enforcement" -DefaultValue "error")
    $tcpListeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)

    if ($tcpListeners.Count -eq 0) {
        $absentCount += 1
        if ($required) {
            $errors.Add("required listener is absent: id=$listenerId port=$port")
        } else {
            Write-Host "RUNTIME_LISTENER_ABSENT id=$listenerId port=$port optional=true"
        }
        continue
    }
    if ($tcpListeners.Count -ne 1) {
        $errors.Add("expected exactly one listener: id=$listenerId port=$port found=$($tcpListeners.Count)")
        continue
    }

    $presentCount += 1
    $tcpListener = $tcpListeners[0]
    $actualBind = [string]$tcpListener.LocalAddress
    if ($actualBind -ne $expectedBind) {
        $bindMessage = "listener bind mismatch: id=$listenerId actual=${actualBind}:$port expected=${expectedBind}:$port"
        if ($bindEnforcement -eq "warn") {
            $warningCount += 1
            Write-Warning $bindMessage
        } else {
            $errors.Add($bindMessage)
        }
    }

    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($tcpListener.OwningProcess)" -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        $errors.Add("listener owner could not be inspected: id=$listenerId pid=$($tcpListener.OwningProcess)")
        continue
    }

    $allowedProcessNames = @($listenerConfig.process_names)
    if ($allowedProcessNames.Count -eq 0 -or [string]$process.Name -notin $allowedProcessNames) {
        $errors.Add("listener process mismatch: id=$listenerId pid=$($process.ProcessId) actual=$($process.Name) allowed=$($allowedProcessNames -join ',')")
    }

    $commandFragments = @($listenerConfig.command_contains)
    $commandLine = [string]$process.CommandLine
    if ($commandFragments.Count -gt 0 -and -not (Test-ContainsAllInsensitive -Text $commandLine -Fragments $commandFragments)) {
        $errors.Add("listener command mismatch: id=$listenerId pid=$($process.ProcessId) required=$($commandFragments -join ',')")
    }

    Write-Host "RUNTIME_LISTENER_PRESENT id=$listenerId bind=${actualBind}:$port pid=$($process.ProcessId) process=$($process.Name)"
}

$allTcpListeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue)
$fullAppProcesses = @(
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -in $fullAppProcessNames -and
            $_.CommandLine -and
            (Test-ContainsAllInsensitive -Text ([string]$_.CommandLine) -Fragments $fullAppSignature)
        }
)
foreach ($process in $fullAppProcesses) {
    $ownedListeners = @($allTcpListeners | Where-Object { $_.OwningProcess -eq $process.ProcessId })
    foreach ($tcpListener in $ownedListeners) {
        $port = [int]$tcpListener.LocalPort
        if (-not $allowedFullAppPorts.ContainsKey($port)) {
            $registeredRole = if ($registeredPorts.ContainsKey($port)) { $registeredPorts[$port] } else { "unregistered" }
            $errors.Add("full application owns forbidden listener: pid=$($process.ProcessId) bind=$($tcpListener.LocalAddress):$port registeredRole=$registeredRole")
        }
    }
}

if ($errors.Count -gt 0) {
    foreach ($message in $errors) {
        Write-Host "RUNTIME_LISTENER_ERROR $message"
    }
    throw "Runtime listener ownership validation failed with $($errors.Count) error(s)."
}

Write-Host "RUNTIME_LISTENERS_OK roles=$($listeners.Count) present=$presentCount absent=$absentCount fullAppProcesses=$($fullAppProcesses.Count) warnings=$warningCount"
