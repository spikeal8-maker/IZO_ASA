[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 65535)]
    [int]$ProxyPort,
    [string]$ServiceName = 'IZOBackend',
    [string]$ServiceXml = 'C:\IZO_ASA\runtime\services\backend\IZOBackend.xml',
    [string]$ServiceWrapper = 'C:\IZO_ASA\runtime\services\backend\IZOBackend.exe',
    [string]$RoleConfig = 'C:\IZO_ASA\config\server-role.json',
    [string]$RollbackRoot = 'C:\IZO_ASA\rollback',
    [string]$HealthPath = 'C:\IZO_ASA\health\socks5-egress-current.json',
    [string]$ProbeScript = (Join-Path $PSScriptRoot 'probe_socks5_egress.py'),
    [string]$LocalHealthUri = 'http://127.0.0.1:8000/api/health',
    [string]$PublicHealthUri = 'https://izo.alikinas.ru/api/health',
    [int]$HealthTimeoutSeconds = 60
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$proxyUrl = "socks5://127.0.0.1:$ProxyPort"
$noProxy = '127.0.0.1,localhost,::1'
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$rollback = Join-Path $RollbackRoot "socks5-egress-$timestamp"
$status = [ordered]@{
    CheckedAt = [DateTimeOffset]::Now.ToString('o')
    Status = 'RUNNING'
    Stage = 'preflight'
    ProxyEndpoint = "127.0.0.1:$ProxyPort"
    RollbackPath = $rollback
    Error = $null
}

function Write-Status {
    param([string]$State, [string]$Stage, [string]$ErrorMessage = '')
    $status.CheckedAt = [DateTimeOffset]::Now.ToString('o')
    $status.Status = $State
    $status.Stage = $Stage
    $status.Error = if ($ErrorMessage) { $ErrorMessage } else { $null }
    $directory = Split-Path -Parent $HealthPath
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $temporary = "$HealthPath.tmp"
    $status | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $HealthPath -Force
}

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Administrator rights are required to update and restart the production service.'
    }
}

function Assert-NoBlockingOperation {
    $blocking = @(
        'C:\IZO_ASA\runtime\update.lock',
        'C:\IZO_ASA\runtime\project-update.lock',
        'C:\IZO_ASA\runtime\promotion.lock',
        'C:\IZO_ASA\runtime\local-backup.lock',
        'C:\IZO_ASA\runtime\future-primary-outbound.lock'
    ) | Where-Object { Test-Path -LiteralPath $_ }
    if ($blocking.Count -gt 0) {
        throw "A protected operation is active: $($blocking -join ', ')"
    }
}

function Set-ServiceEnvironmentValue {
    param([xml]$Document, [string]$Name, [string]$Value)
    $node = @($Document.service.env | Where-Object { [string]$_.name -eq $Name }) | Select-Object -First 1
    if ($null -eq $node) {
        $node = $Document.CreateElement('env')
        [void]$node.SetAttribute('name', $Name)
        [void]$Document.service.AppendChild($node)
    }
    [void]$node.SetAttribute('value', $Value)
}

function Wait-Healthy {
    param([string]$Uri, [int]$TimeoutSeconds)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-RestMethod -Uri $Uri -TimeoutSec 10
            if ($response.ready -eq $true) { return }
        } catch {}
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw "Health endpoint did not become ready: $Uri"
}

function Restart-Backend {
    & $ServiceWrapper stop
    if ($LASTEXITCODE -ne 0) { throw "Backend stop failed with exit code $LASTEXITCODE." }
    & $ServiceWrapper start
    if ($LASTEXITCODE -ne 0) { throw "Backend start failed with exit code $LASTEXITCODE." }
}

$changed = $false
try {
    Assert-Administrator
    Assert-NoBlockingOperation
    foreach ($path in @($ServiceXml, $ServiceWrapper, $RoleConfig, $ProbeScript)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required file is missing: $path" }
    }
    $role = Get-Content -LiteralPath $RoleConfig -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($role.role -ne 'PRIMARY' -or $role.databaseWriter -ne $true) {
        throw 'Production role is not PRIMARY/databaseWriter=true; no service change was made.'
    }

    $listener = Get-NetTCPConnection -State Listen -LocalPort $ProxyPort -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalAddress -in @('127.0.0.1', '::1') } |
        Select-Object -First 1
    if ($null -eq $listener) { throw "No loopback listener exists on SOCKS5 port $ProxyPort." }
    $listenerProcess = Get-Process -Id $listener.OwningProcess -ErrorAction Stop
    if ($listenerProcess.ProcessName -ne 'AdGuardVpnSvc') {
        throw "SOCKS5 port $ProxyPort is owned by $($listenerProcess.ProcessName), not AdGuardVpnSvc."
    }

    $xml = [xml](Get-Content -LiteralPath $ServiceXml -Raw -Encoding UTF8)
    $python = [string]$xml.service.executable
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Configured Backend Python is missing: $python"
    }
    & $python $ProbeScript --proxy-url $proxyUrl
    if ($LASTEXITCODE -ne 0) { throw "SOCKS5 reachability probe failed with exit code $LASTEXITCODE." }

    New-Item -ItemType Directory -Path $rollback -Force | Out-Null
    Copy-Item -LiteralPath $ServiceXml -Destination (Join-Path $rollback 'IZOBackend.xml') -Force
    Set-ServiceEnvironmentValue -Document $xml -Name 'ALL_PROXY' -Value $proxyUrl
    Set-ServiceEnvironmentValue -Document $xml -Name 'NO_PROXY' -Value $noProxy
    $xml.Save($ServiceXml)
    $changed = $true
    Write-Status -State 'RUNNING' -Stage 'restart'

    Restart-Backend
    Wait-Healthy -Uri $LocalHealthUri -TimeoutSeconds $HealthTimeoutSeconds
    Wait-Healthy -Uri $PublicHealthUri -TimeoutSeconds $HealthTimeoutSeconds
    Write-Status -State 'OK' -Stage 'verified'
    Write-Output "SOCKS5_EGRESS_OK proxy=127.0.0.1:$ProxyPort rollback=$rollback"
} catch {
    $message = $_.Exception.Message
    if ($changed -and (Test-Path -LiteralPath (Join-Path $rollback 'IZOBackend.xml'))) {
        Copy-Item -LiteralPath (Join-Path $rollback 'IZOBackend.xml') -Destination $ServiceXml -Force
        try { Restart-Backend } catch {}
    }
    Write-Status -State 'ERROR' -Stage 'rollback' -ErrorMessage $message
    throw
}
