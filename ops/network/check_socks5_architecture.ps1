[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 65535)]
    [int]$ProxyPort,
    [string]$FrpServerAddress = '161.104.46.160',
    [int]$FrpServerPort = 7000,
    [string]$PublicHealthUri = 'https://izo.alikinas.ru/api/health'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$errors = [System.Collections.Generic.List[string]]::new()

$listener = Get-NetTCPConnection -State Listen -LocalPort $ProxyPort -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalAddress -in @('127.0.0.1', '::1') } |
    Select-Object -First 1
$listenerOwner = if ($listener) { (Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue).ProcessName } else { $null }
if (-not $listener) { $errors.Add('socks5_listener_missing') }
elseif ($listenerOwner -ne 'AdGuardVpnSvc') { $errors.Add('socks5_listener_owner_invalid') }

$frpProcesses = @(Get-Process -Name frpc -ErrorAction SilentlyContinue)
if ($frpProcesses.Count -ne 1) { $errors.Add('frpc_process_count_invalid') }
$frpConnections = @()
if ($frpProcesses.Count -eq 1) {
    $frpConnections = @(Get-NetTCPConnection -OwningProcess $frpProcesses[0].Id -State Established -ErrorAction SilentlyContinue |
        Where-Object { $_.RemoteAddress -eq $FrpServerAddress -and $_.RemotePort -eq $FrpServerPort })
    if ($frpConnections.Count -ne 1) { $errors.Add('frpc_connection_count_invalid') }
}

$physicalInterfaceIndexes = @(Get-NetAdapter -IncludeHidden -ErrorAction SilentlyContinue |
    Where-Object { $_.HardwareInterface -eq $true -and $_.Status -eq 'Up' } |
    Select-Object -ExpandProperty ifIndex -Unique)
$physicalAddresses = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike '127.*' -and $_.InterfaceIndex -in $physicalInterfaceIndexes } |
    Select-Object -ExpandProperty IPAddress -Unique)
$frpDirect = $frpConnections.Count -eq 1 -and $frpConnections[0].LocalAddress -in $physicalAddresses
if (-not $frpDirect) { $errors.Add('frpc_not_bound_to_physical_interface') }

$yandexRoute = Test-NetConnection disk.yandex.ru -Port 443 -InformationLevel Detailed -WarningAction SilentlyContinue
$yandexAdapter = Get-NetAdapter -Name ([string]$yandexRoute.InterfaceAlias) -ErrorAction SilentlyContinue
$yandexDirect = (
    $yandexRoute.TcpTestSucceeded -and
    $null -ne $yandexAdapter -and
    $yandexAdapter.HardwareInterface -eq $true -and
    $yandexRoute.InterfaceAlias -notmatch '(?i)AdGuard|VPN'
)
if (-not $yandexDirect) { $errors.Add('yandex_route_not_direct') }

$publicReady = $false
try {
    $public = Invoke-RestMethod -Uri $PublicHealthUri -TimeoutSec 15
    $publicReady = $public.ready -eq $true
} catch {}
if (-not $publicReady) { $errors.Add('public_health_not_ready') }

$result = [ordered]@{
    CheckedAt = [DateTimeOffset]::Now.ToString('o')
    Ok = $errors.Count -eq 0
    Socks5 = [ordered]@{
        Endpoint = "127.0.0.1:$ProxyPort"
        Owner = $listenerOwner
        Listening = [bool]$listener
    }
    Frp = [ordered]@{
        ProcessCount = $frpProcesses.Count
        ConnectionCount = $frpConnections.Count
        LocalAddress = if ($frpConnections.Count -eq 1) { $frpConnections[0].LocalAddress } else { $null }
        Direct = $frpDirect
    }
    Yandex = [ordered]@{
        HttpsReachable = [bool]$yandexRoute.TcpTestSucceeded
        InterfaceAlias = [string]$yandexRoute.InterfaceAlias
        Direct = $yandexDirect
    }
    PublicReady = $publicReady
    Errors = @($errors)
}
$result | ConvertTo-Json -Depth 5
if ($errors.Count -gt 0) { exit 1 }
