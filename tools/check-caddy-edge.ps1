[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$ReleasePath = "",
    [string]$ReleaseId = "",
    [string]$PublicBaseUrl = "",
    [switch]$ConfigOnly,
    [switch]$PlanOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if (-not $RepoRoot.Trim()) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$root = (Resolve-Path -LiteralPath $RepoRoot).Path
. (Join-Path $root "tools\caddy-runtime.ps1")
$runtime = Get-IzoCaddyRuntime -RepoRoot $root
$activeManifestPath = Join-Path $root ".runtime\active-frontend.json"
$active = $null
$activeAccessLog = ""
if (-not $ReleasePath.Trim()) {
    if (-not (Test-Path -LiteralPath $activeManifestPath -PathType Leaf)) {
        throw "Active frontend manifest is required when ReleasePath is omitted."
    }
    $active = Get-Content -LiteralPath $activeManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $ReleasePath = [string]$active.release_path
    $ReleaseId = [string]$active.active_release
    if ($active.PSObject.Properties.Name -contains "access_log") {
        $activeAccessLog = [string]$active.access_log
    }
}
if (-not $ReleaseId.Trim()) {
    $ReleaseId = "config-validation"
}

if ($PlanOnly) {
    Write-Host "CADDY_EDGE_PLAN version=$($runtime.Version) config=$($runtime.ConfigPath) release=$ReleasePath"
    Write-Host "CADDY_EDGE_PLAN_STEP validate=true bind=127.0.0.1:$($runtime.ProductionPort) hostAllowlist=izo.alikinas.ru,127.0.0.1,localhost"
    if (-not $ConfigOnly) {
        Write-Host "CADDY_EDGE_PLAN_STEP live=true release=$ReleaseId routes=/,/feed,/gallery,/api/version headers=security,cache,compression logs=redacted-json"
    }
    Write-Host "CADDY_EDGE_PLAN_OK configOnly=$ConfigOnly"
    return
}

Assert-IzoCaddyRuntime -Runtime $runtime
$environment = Set-IzoCaddyEnvironment `
    -Runtime $runtime `
    -ReleasePath $ReleasePath `
    -ReleaseId $ReleaseId `
    -Port $runtime.ProductionPort `
    -AdminAddress $runtime.ProductionAdminAddress `
    -Scope $(if ($ConfigOnly) { "validation" } else { "production" })
Invoke-IzoCaddyValidate -Runtime $runtime
if ($ConfigOnly) {
    Write-Host "CADDY_EDGE_CONFIG_OK version=$($runtime.Version) releasePath=$($environment.ReleasePath)"
    return
}

$listenerState = Get-IzoFrontendListenerState -Runtime $runtime -Port $runtime.ProductionPort
if ($listenerState.Kind -ne "caddy") {
    throw "Production frontend listener is not the pinned Caddy runtime: kind=$($listenerState.Kind)"
}
if ([string]$listenerState.Listener.LocalAddress -ne "127.0.0.1") {
    throw "Caddy production listener is not bound to IPv4 loopback."
}
if (-not (Test-IzoCaddyReleaseReady -Port $runtime.ProductionPort -ReleaseId $ReleaseId -Attempts 4)) {
    throw "Caddy does not serve the active release marker."
}

function Invoke-EdgeRequest {
    param(
        [string]$Path,
        [string]$HostName = "izo.alikinas.ru",
        [hashtable]$Headers = @{}
    )

    $requestHeaders = @{ Host = $HostName }
    foreach ($key in $Headers.Keys) { $requestHeaders[$key] = $Headers[$key] }
    try {
        $response = Invoke-WebRequest "http://127.0.0.1:$($runtime.ProductionPort)$Path" -Headers $requestHeaders -UseBasicParsing -TimeoutSec 10
        return [pscustomobject]@{ Status = [int]$response.StatusCode; Response = $response }
    } catch {
        if ($_.Exception.Response) {
            return [pscustomobject]@{ Status = [int]$_.Exception.Response.StatusCode; Response = $_.Exception.Response }
        }
        throw
    }
}

$rootResponse = Invoke-EdgeRequest -Path "/?token=edge-query-sentinel&userId=edge-user-id" -Headers @{
    Authorization = "Bearer edge-secret-sentinel"
    Cookie = "onenode_session=edge-cookie-sentinel"
}
if ($rootResponse.Status -ne 200) { throw "Caddy root smoke failed: $($rootResponse.Status)" }
$securityHeaders = @{
    "X-Content-Type-Options" = "nosniff"
    "Referrer-Policy" = "strict-origin-when-cross-origin"
    "X-Frame-Options" = "SAMEORIGIN"
    "X-Permitted-Cross-Domain-Policies" = "none"
    "Strict-Transport-Security" = "max-age=31536000"
    "Content-Security-Policy" = "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'self'; form-action 'self'; img-src 'self' data: blob: https:; media-src 'self' blob: https:; connect-src 'self' https: wss:; script-src 'self' 'unsafe-inline' https://st.max.ru; style-src 'self' 'unsafe-inline'; font-src 'self' data: https:; worker-src 'self' blob:"
}
foreach ($entry in $securityHeaders.GetEnumerator()) {
    if ([string]$rootResponse.Response.Headers[$entry.Key] -ne $entry.Value) {
        throw "Caddy security header mismatch: $($entry.Key)"
    }
}
if ([string]$rootResponse.Response.Headers["Server"]) { throw "Caddy leaked a Server response header." }
if ([string]$rootResponse.Response.Headers["Cache-Control"] -ne "no-store") { throw "SPA HTML is not no-store." }

foreach ($allowedHost in @("127.0.0.1:$($runtime.ProductionPort)", "localhost:$($runtime.ProductionPort)")) {
    if ((Invoke-EdgeRequest -Path "/" -HostName $allowedHost).Status -ne 200) {
        throw "Allowed local Host failed: $allowedHost"
    }
}
foreach ($blockedHost in @("sub.izo.alikinas.ru", "evil.example")) {
    if ((Invoke-EdgeRequest -Path "/" -HostName $blockedHost).Status -ne 421) {
        throw "Untrusted Host was not rejected: $blockedHost"
    }
}

$html = [string]$rootResponse.Response.Content
$assetMatch = [regex]::Match($html, '(?:src|href)="(?<path>/assets/[^"?]+\.(?:js|css))"')
if (-not $assetMatch.Success) { throw "Hashed frontend asset was not found in index.html." }
$assetResponse = Invoke-EdgeRequest -Path $assetMatch.Groups["path"].Value
if ($assetResponse.Status -ne 200) { throw "Hashed asset smoke failed." }
if ([string]$assetResponse.Response.Headers["Cache-Control"] -ne "public, max-age=31536000, immutable") {
    throw "Hashed asset cache policy is not immutable."
}

foreach ($route in @("/feed", "/gallery")) {
    $response = Invoke-EdgeRequest -Path $route
    if ($response.Status -ne 200 -or [string]$response.Response.Headers["X-IZO-Release"] -ne $ReleaseId) {
        throw "Backend-owned shell route failed release identity: $route"
    }
}
$versionResponse = Invoke-EdgeRequest -Path "/api/version"
if ($versionResponse.Status -ne 200) { throw "Caddy API proxy smoke failed." }
$version = $versionResponse.Response.Content | ConvertFrom-Json
if ([string]$version.release_id -ne $ReleaseId -or [string]$version.frontend_build -ne $ReleaseId) {
    throw "Caddy API release identity does not match the active frontend."
}

Add-Type -AssemblyName System.Net.Http
$httpHandler = New-Object System.Net.Http.HttpClientHandler
$httpClient = New-Object System.Net.Http.HttpClient($httpHandler)
try {
    $compressionRequest = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Get, "http://127.0.0.1:$($runtime.ProductionPort)/")
    $compressionRequest.Headers.Host = "izo.alikinas.ru"
    $compressionRequest.Headers.AcceptEncoding.ParseAdd("gzip")
    $compressionResponse = $httpClient.SendAsync($compressionRequest).GetAwaiter().GetResult()
    if (-not ($compressionResponse.Content.Headers.ContentEncoding -contains "gzip")) {
        throw "Caddy compression smoke did not return gzip."
    }
} finally {
    $httpClient.Dispose()
    $httpHandler.Dispose()
}

Start-Sleep -Milliseconds 200
$accessLog = if ($activeAccessLog.Trim()) { [IO.Path]::GetFullPath($activeAccessLog) } else { $environment.AccessLog }
if (-not (Test-Path -LiteralPath $accessLog -PathType Leaf)) { throw "Caddy access log was not created." }
$recentLog = (Get-Content -LiteralPath $accessLog -Tail 40 -ErrorAction Stop) -join "`n"
if (-not $recentLog.Trim()) { throw "Caddy access log is empty." }
foreach ($sentinel in @("edge-secret-sentinel", "edge-cookie-sentinel", "edge-query-sentinel", "edge-user-id")) {
    if ($recentLog.Contains($sentinel)) { throw "Caddy access log leaked redaction sentinel: $sentinel" }
}
$lastJsonLine = @(Get-Content -LiteralPath $accessLog -Tail 40 | Where-Object { $_.Trim() })[-1]
try { $null = $lastJsonLine | ConvertFrom-Json } catch { throw "Caddy access log is not structured JSON." }

if ($PublicBaseUrl.Trim()) {
    if ($PublicBaseUrl -notmatch '^https://') { throw "Public Caddy smoke requires an HTTPS URL." }
    $public = Invoke-WebRequest ($PublicBaseUrl.TrimEnd("/") + "/api/health") -UseBasicParsing -TimeoutSec 15
    if ($public.StatusCode -ne 200) { throw "Public TLS smoke failed." }
    foreach ($entry in $securityHeaders.GetEnumerator()) {
        if ([string]$public.Headers[$entry.Key] -ne $entry.Value) {
            throw "Public security header mismatch: $($entry.Key)"
        }
    }
    if ([string]$public.Headers["Server"]) { throw "Public response leaked a Server header." }
    Write-Host "CADDY_PUBLIC_TLS_OK url=$PublicBaseUrl"
}

Write-Host "CADDY_EDGE_OK version=$($runtime.Version) release=$ReleaseId pid=$($listenerState.Process.ProcessId) bind=127.0.0.1:$($runtime.ProductionPort)"
