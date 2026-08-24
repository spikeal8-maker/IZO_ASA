[CmdletBinding()]
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$ExpectedCommit,
    [string]$DestinationPath = 'C:\IZO_ASA\runtime\promote-project-release.ps1',
    [string]$BackupRoot = 'C:\IZO_ASA\rollback',
    [string]$ReceiptPath = 'C:\IZO_ASA\health\promoter-install-current.json',
    [string]$GitPath = 'C:\Users\admins\AppData\Local\Programs\Git\cmd\git.exe',
    [switch]$PlanOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-GitText {
    param([string[]]$Arguments)

    $output = & $GitPath -C $RepoRoot @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Git command failed with exit code $LASTEXITCODE."
    }
    return (($output | Out-String).Trim())
}

function Get-NormalizedSha256 {
    param([string]$Path)

    $text = [IO.File]::ReadAllText($Path).Replace("`r`n", "`n")
    $bytes = [Text.Encoding]::UTF8.GetBytes($text)
    $hash = [Security.Cryptography.SHA256]::HashData($bytes)
    return 'sha256:' + [Convert]::ToHexString($hash).ToLowerInvariant()
}

$resolvedRepo = (Resolve-Path -LiteralPath $RepoRoot).Path
$sourcePath = Join-Path $resolvedRepo 'ops\release\promote-project-release.ps1'
$installerPath = Join-Path $resolvedRepo 'ops\release\install-project-promoter.ps1'
foreach ($required in @($sourcePath, $installerPath, $GitPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required installer input is missing: $required"
    }
}

$actualCommit = Invoke-GitText -Arguments @('rev-parse', 'HEAD')
if ($actualCommit -notmatch '^[0-9a-fA-F]{40}$' -or
    -not $actualCommit.Equals($ExpectedCommit, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Checked-out commit does not match ExpectedCommit."
}

& $GitPath -C $resolvedRepo diff --quiet --exit-code
if ($LASTEXITCODE -ne 0) {
    throw 'Tracked working tree changes are present; refusing promoter installation.'
}
& $GitPath -C $resolvedRepo diff --cached --quiet --exit-code
if ($LASTEXITCODE -ne 0) {
    throw 'Staged changes are present; refusing promoter installation.'
}
$untracked = Invoke-GitText -Arguments @('ls-files', '--others', '--exclude-standard')
if ($untracked) {
    throw 'Untracked files are present; refusing promoter installation.'
}

$sourceHash = Get-NormalizedSha256 -Path $sourcePath
if ($PlanOnly) {
    Write-Host "PROMOTER_INSTALL_PLAN_OK commit=$actualCommit source=$sourceHash"
    exit 0
}

$destinationDirectory = Split-Path -Parent $DestinationPath
$receiptDirectory = Split-Path -Parent $ReceiptPath
foreach ($directory in @($destinationDirectory, $BackupRoot, $receiptDirectory)) {
    [IO.Directory]::CreateDirectory($directory) | Out-Null
}

$timestamp = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss')
$backupPath = Join-Path $BackupRoot "promote-project-release-$timestamp-$($actualCommit.Substring(0, 12)).ps1"
$temporaryPath = Join-Path $destinationDirectory ".promote-project-release.installing-$PID.ps1"
$hadPrevious = Test-Path -LiteralPath $DestinationPath -PathType Leaf
$replacedDestination = $false

try {
    if ($hadPrevious) {
        Copy-Item -LiteralPath $DestinationPath -Destination $backupPath -Force
    }
    Copy-Item -LiteralPath $sourcePath -Destination $temporaryPath -Force
    $temporaryHash = Get-NormalizedSha256 -Path $temporaryPath
    if ($temporaryHash -ne $sourceHash) {
        throw 'Temporary promoter copy does not match tracked source.'
    }
    Move-Item -LiteralPath $temporaryPath -Destination $DestinationPath -Force
    $replacedDestination = $true
    $installedHash = Get-NormalizedSha256 -Path $DestinationPath
    if ($installedHash -ne $sourceHash) {
        throw 'Installed promoter does not match tracked source.'
    }

    $receipt = [ordered]@{
        schema = 'izo.promoter-install.v1'
        installed_at_utc = (Get-Date).ToUniversalTime().ToString('o')
        commit = $actualCommit.ToLowerInvariant()
        source_sha256 = $sourceHash
        installed_sha256 = $installedHash
        destination = $DestinationPath
        previous_backup = if ($hadPrevious) { $backupPath } else { $null }
        services_restarted = $false
    }
    $receiptTemporary = "$ReceiptPath.tmp-$PID"
    $receipt | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $receiptTemporary -Encoding utf8
    Move-Item -LiteralPath $receiptTemporary -Destination $ReceiptPath -Force
} catch {
    if (Test-Path -LiteralPath $temporaryPath) {
        Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
    }
    if ($replacedDestination) {
        if ($hadPrevious -and (Test-Path -LiteralPath $backupPath -PathType Leaf)) {
            Copy-Item -LiteralPath $backupPath -Destination $DestinationPath -Force
        } elseif (-not $hadPrevious -and (Test-Path -LiteralPath $DestinationPath)) {
            Remove-Item -LiteralPath $DestinationPath -Force -ErrorAction SilentlyContinue
        }
    }
    throw
}

Write-Host "PROMOTER_INSTALL_OK commit=$actualCommit sha=$sourceHash backup=$backupPath servicesRestarted=false"
