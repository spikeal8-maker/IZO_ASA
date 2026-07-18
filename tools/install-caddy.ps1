[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [switch]$PlanOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if (-not $RepoRoot.Trim()) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$root = (Resolve-Path -LiteralPath $RepoRoot).Path
$specPath = Join-Path $root "ops\caddy\runtime.json"
if (-not (Test-Path -LiteralPath $specPath -PathType Leaf)) {
    throw "Pinned Caddy runtime specification was not found: $specPath"
}
$spec = Get-Content -LiteralPath $specPath -Raw -Encoding UTF8 | ConvertFrom-Json
$installPath = [IO.Path]::GetFullPath((Join-Path $root ([string]$spec.install_relative_path)))
$installRoot = [IO.Path]::GetFullPath((Join-Path $root ".tools\caddy")).TrimEnd("\")
$temporaryRoot = [IO.Path]::GetFullPath((Join-Path $root ".runtime\caddy-install")).TrimEnd("\")

function Get-InstallerSha256 {
    param([string]$Path)

    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        return (($algorithm.ComputeHash($stream) | ForEach-Object { $_.ToString("x2") }) -join "")
    } finally {
        $stream.Dispose()
        $algorithm.Dispose()
    }
}

function Test-InstallerPathWithin {
    param([string]$Path, [string]$Parent)

    $fullPath = [IO.Path]::GetFullPath($Path)
    $fullParent = [IO.Path]::GetFullPath($Parent).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    return $fullPath.StartsWith($fullParent + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
}

if (-not (Test-InstallerPathWithin -Path $installPath -Parent $installRoot)) {
    throw "Pinned Caddy install path escapes the canonical tool directory."
}
if ([string]$spec.download_url -notlike "https://github.com/caddyserver/caddy/releases/download/*") {
    throw "Caddy download URL is not an official pinned GitHub release asset."
}
if ([string]$spec.archive_sha256 -notmatch "^[0-9a-f]{64}$" -or [string]$spec.executable_sha256 -notmatch "^[0-9a-f]{64}$") {
    throw "Pinned Caddy hashes are invalid."
}

if ($PlanOnly) {
    Write-Host "CADDY_INSTALL_PLAN version=$($spec.version) platform=$($spec.platform) destination=$installPath"
    Write-Host "CADDY_INSTALL_PLAN_SOURCE url=$($spec.download_url) archiveSha256=$($spec.archive_sha256) executableSha256=$($spec.executable_sha256)"
    Write-Host "CADDY_INSTALL_PLAN_OK networkOnlyWhenMissing=true"
    return
}

if (Test-Path -LiteralPath $installPath -PathType Leaf) {
    $existingHash = Get-InstallerSha256 -Path $installPath
    if ($existingHash -ne [string]$spec.executable_sha256) {
        throw "Installed Caddy executable hash does not match the pinned runtime."
    }
    $existingVersion = [string](@(& $installPath version 2>&1)[0])
    if ($existingVersion -notlike "v$($spec.version) *") {
        throw "Installed Caddy version does not match the pinned runtime: $existingVersion"
    }
    Write-Host "CADDY_INSTALL_OK version=$($spec.version) path=$installPath sha256=$existingHash existing=true"
    return
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $installPath), $temporaryRoot | Out-Null
$operationRoot = Join-Path $temporaryRoot ([guid]::NewGuid().ToString("N"))
if (-not (Test-InstallerPathWithin -Path $operationRoot -Parent $temporaryRoot)) {
    throw "Temporary Caddy install directory escaped the canonical runtime directory."
}
New-Item -ItemType Directory -Force -Path $operationRoot | Out-Null
try {
    $archivePath = Join-Path $operationRoot ([string]$spec.archive_name)
    Invoke-WebRequest -Uri ([string]$spec.download_url) -OutFile $archivePath -UseBasicParsing
    $archiveHash = Get-InstallerSha256 -Path $archivePath
    if ($archiveHash -ne [string]$spec.archive_sha256) {
        throw "Downloaded Caddy archive hash mismatch."
    }
    $expandedPath = Join-Path $operationRoot "expanded"
    Expand-Archive -LiteralPath $archivePath -DestinationPath $expandedPath
    $candidatePath = Join-Path $expandedPath "caddy.exe"
    if (-not (Test-Path -LiteralPath $candidatePath -PathType Leaf)) {
        throw "Official Caddy archive did not contain caddy.exe."
    }
    $candidateHash = Get-InstallerSha256 -Path $candidatePath
    if ($candidateHash -ne [string]$spec.executable_sha256) {
        throw "Extracted Caddy executable hash mismatch."
    }
    $candidateVersion = [string](@(& $candidatePath version 2>&1)[0])
    if ($candidateVersion -notlike "v$($spec.version) *") {
        throw "Extracted Caddy version mismatch: $candidateVersion"
    }
    $stagedInstallPath = "$installPath.new"
    Copy-Item -LiteralPath $candidatePath -Destination $stagedInstallPath -Force
    if ((Get-InstallerSha256 -Path $stagedInstallPath) -ne [string]$spec.executable_sha256) {
        throw "Staged Caddy executable failed its final integrity check."
    }
    Move-Item -LiteralPath $stagedInstallPath -Destination $installPath -Force
    Write-Host "CADDY_INSTALL_OK version=$($spec.version) path=$installPath sha256=$candidateHash existing=false"
} finally {
    if ((Test-Path -LiteralPath $operationRoot) -and (Test-InstallerPathWithin -Path $operationRoot -Parent $temporaryRoot)) {
        Remove-Item -LiteralPath $operationRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
