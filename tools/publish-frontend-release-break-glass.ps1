[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$Reason = "",
    [string]$Operator = "",
    [string]$Acknowledgement = "",
    [switch]$PlanOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$requiredAcknowledgement = "I_ACCEPT_UNVERIFIED_RELEASE_RISK"

if (-not $RepoRoot.Trim()) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent ([string]$MyInvocation.MyCommand.Path))
}
$root = (Resolve-Path -LiteralPath $RepoRoot).Path
$publisher = Join-Path $root "tools\publish-frontend-release.ps1"
$launcher = Join-Path $root "start-public.bat"
if (
    -not (Test-Path -LiteralPath $publisher -PathType Leaf) -or
    -not (Test-Path -LiteralPath $launcher -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $root "backend\main.py") -PathType Leaf)
) {
    throw "Refusing break-glass release outside the canonical project."
}
if ($Reason.Trim().Length -lt 20) {
    throw "Break-glass Reason must contain at least 20 characters."
}
if ($Operator.Trim().Length -lt 3) {
    throw "Break-glass Operator must contain at least 3 characters."
}
if ($Acknowledgement -ne $requiredAcknowledgement) {
    throw "Break-glass acknowledgement must equal $requiredAcknowledgement"
}

$shaOutput = @(& git.exe -C $root rev-parse HEAD)
$shaExitCode = $LASTEXITCODE
$branchOutput = @(& git.exe -C $root branch --show-current)
$branchExitCode = $LASTEXITCODE
$sha = if ($shaOutput.Count -gt 0) { ([string]$shaOutput[0]).Trim() } else { "" }
$branch = if ($branchOutput.Count -gt 0) { ([string]$branchOutput[0]).Trim() } else { "" }
if ($shaExitCode -ne 0 -or $branchExitCode -ne 0 -or $sha -notmatch "^[0-9a-f]{40}$") {
    throw "Break-glass release requires a valid Git checkout."
}
if (-not $PlanOnly -and $branch -ne "main") {
    throw "Break-glass release requires a valid main checkout."
}
if ($PlanOnly -and -not $branch) { $branch = "detached" }
if (@(& git.exe -C $root status --porcelain).Count -gt 0 -and -not $PlanOnly) {
    throw "Break-glass release still requires a clean checkout."
}

$auditRoot = Join-Path $root ".runtime\audit\release-break-glass"
$authorizationRoot = Join-Path $auditRoot "authorizations"
$auditLog = Join-Path $auditRoot "release-break-glass.jsonl"
if ($PlanOnly) {
    Write-Host "BREAK_GLASS_PLAN root=$root sha=$sha branch=$branch operator=$($Operator.Trim()) reasonLength=$($Reason.Trim().Length)"
    Write-Host "BREAK_GLASS_PLAN_STEP acknowledgement=$requiredAcknowledgement"
    Write-Host "BREAK_GLASS_PLAN_STEP authorization=$authorizationRoot ttlMinutes=10 singleUse=true"
    Write-Host "BREAK_GLASS_PLAN_STEP audit=$auditLog events=requested,completed|failed"
    Write-Host "BREAK_GLASS_PLAN_STEP launcher=$launcher publisher=$publisher verification=unverified-break-glass fullStack=true"
    return
}

[IO.Directory]::CreateDirectory($authorizationRoot) | Out-Null
$authorizationId = [guid]::NewGuid().ToString("N")
$requestedAt = [DateTimeOffset]::UtcNow
$authorizationPath = Join-Path $authorizationRoot "$authorizationId.json"
$authorization = [ordered]@{
    authorization_version = 1
    authorization_type = "release-break-glass-authorization"
    authorization_id = $authorizationId
    git_sha = $sha
    branch = $branch
    operator = $Operator.Trim()
    reason = $Reason.Trim()
    acknowledgement = $requiredAcknowledgement
    machine = [Environment]::MachineName
    windows_user = [Environment]::UserName
    requested_at = $requestedAt.ToString("o")
    expires_at = $requestedAt.AddMinutes(10).ToString("o")
    status = "authorized"
    consumed_at = ""
}
$authorizationTemp = "$authorizationPath.tmp"
$authorization | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $authorizationTemp -Encoding UTF8
Move-Item -LiteralPath $authorizationTemp -Destination $authorizationPath -Force

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
function Write-BreakGlassAuditEvent {
    param(
        [string]$Event,
        [string]$Outcome,
        [string]$ReleaseId = "",
        [string]$ErrorCode = ""
    )

    $row = [ordered]@{
        audit_version = 1
        event = $Event
        outcome = $Outcome
        authorization_id = $authorizationId
        git_sha = $sha
        branch = $branch
        operator = $Operator.Trim()
        reason = $Reason.Trim()
        machine = [Environment]::MachineName
        windows_user = [Environment]::UserName
        release_id = $ReleaseId
        error = $ErrorCode
        occurred_at = [DateTimeOffset]::UtcNow.ToString("o")
    }
    [IO.File]::AppendAllText($auditLog, ($row | ConvertTo-Json -Compress) + [Environment]::NewLine, $utf8NoBom)
}

Write-BreakGlassAuditEvent -Event "requested" -Outcome "authorized"
try {
    $previousAuthorization = [Environment]::GetEnvironmentVariable("IZO_BREAK_GLASS_AUTHORIZATION", "Process")
    $previousNoPause = [Environment]::GetEnvironmentVariable("IZO_NO_PAUSE", "Process")
    try {
        [Environment]::SetEnvironmentVariable("IZO_BREAK_GLASS_AUTHORIZATION", $authorizationPath, "Process")
        [Environment]::SetEnvironmentVariable("IZO_NO_PAUSE", "1", "Process")
        Push-Location -LiteralPath $root
        try {
            & cmd.exe /d /c start-public.bat
            if ($LASTEXITCODE -ne 0) {
                throw "Public launcher returned exit code $LASTEXITCODE."
            }
        } finally {
            Pop-Location
        }
    } finally {
        [Environment]::SetEnvironmentVariable("IZO_BREAK_GLASS_AUTHORIZATION", $previousAuthorization, "Process")
        [Environment]::SetEnvironmentVariable("IZO_NO_PAUSE", $previousNoPause, "Process")
    }
    $active = Get-Content -LiteralPath (Join-Path $root ".runtime\active-frontend.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $activeBackend = Get-Content -LiteralPath (Join-Path $root ".runtime\active-backend.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    if (
        [string]$active.verification_kind -ne "break-glass" -or
        [string]$active.active_release -ne [string]$activeBackend.release_id
    ) {
        throw "Break-glass launcher completed without matching frontend/backend release evidence."
    }
    Write-BreakGlassAuditEvent -Event "completed" -Outcome "success" -ReleaseId ([string]$active.active_release)
    Write-Host "BREAK_GLASS_RELEASE_OK authorization=$authorizationId release=$($active.active_release) audit=$auditLog"
} catch {
    $message = [string]$_.Exception.Message
    if ($message.Length -gt 500) { $message = $message.Substring(0, 500) }
    Write-BreakGlassAuditEvent -Event "failed" -Outcome "failure" -ErrorCode $message
    throw
}
