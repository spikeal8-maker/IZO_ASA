[CmdletBinding()]
param(
    [ValidateSet("", "acquire", "release", "status")]
    [string]$Action = "",
    [string]$RepoRoot = "",
    [string]$Kind = "",
    [string]$Token = "",
    [string]$Command = "",
    [string]$TokenOutFile = "",
    [ValidateSet("worktree", "common-repository")]
    [string]$StorageScope = "worktree",
    [int]$OwnerProcessId = 0
)

# REL-LOCK-001: single-flight repository operations.
#
# Dot-source this file to use the library functions, or run it with -Action
# for batch launchers that cannot dot-source PowerShell:
#   acquire  - take the lock on behalf of the calling launcher process chain
#              and write the re-entrancy token to -TokenOutFile.
#   release  - release the lock when the caller presents the matching token.
#   status   - print the current owner metadata without mutating anything.
#
# The default lock is a directory under .runtime\locks\<kind>. Acquisition is
# atomic. common-repository scope instead stores it under the Git common dir so
# sibling worktrees contend on the same lock.

Set-StrictMode -Version Latest

function Get-IzoRepositoryLockTokenVariable {
    param([string]$Kind)

    return "IZO_REPO_LOCK_TOKEN_" + ($Kind.ToUpperInvariant() -replace "-", "_")
}

function Get-IzoRepositoryLockPath {
    param(
        [string]$RepoRoot,
        [string]$Kind,
        [ValidateSet("worktree", "common-repository")]
        [string]$StorageScope = "worktree"
    )

    if ($Kind -notmatch "^[a-z0-9][a-z0-9-]{0,63}$") {
        throw "Repository operation lock kind must be a short lowercase slug: '$Kind'"
    }
    if ($StorageScope -eq "common-repository") {
        $gitCommand = Get-Command git.exe -ErrorAction SilentlyContinue
        if ($null -eq $gitCommand) { $gitCommand = Get-Command git -ErrorAction Stop }
        $commonOutput = @(& $gitCommand.Source -C $RepoRoot rev-parse --git-common-dir 2>$null)
        $gitExitCode = $LASTEXITCODE
        $commonDir = $commonOutput | Select-Object -First 1
        if ($gitExitCode -ne 0 -or -not ([string]$commonDir).Trim()) {
            throw "Git common directory could not be resolved for repository: $RepoRoot"
        }
        $commonPath = if ([IO.Path]::IsPathRooted(([string]$commonDir).Trim())) {
            [IO.Path]::GetFullPath(([string]$commonDir).Trim())
        } else {
            [IO.Path]::GetFullPath((Join-Path $RepoRoot ([string]$commonDir).Trim()))
        }
        return Join-Path (Join-Path (Join-Path $commonPath "izo-agent") "locks") $Kind
    }
    return Join-Path (Join-Path $RepoRoot ".runtime\locks") $Kind
}

function Get-IzoProcessStartText {
    param([int]$ProcessId)

    try {
        return [System.Diagnostics.Process]::GetProcessById($ProcessId).StartTime.ToUniversalTime().ToString("o")
    } catch {
        return ""
    }
}

function Get-IzoRepositoryLockOwner {
    param([string]$LockPath)

    $ownerFile = Join-Path $LockPath "owner.json"
    if (-not (Test-Path -LiteralPath $ownerFile -PathType Leaf)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $ownerFile -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Test-IzoRepositoryLockStale {
    param([pscustomobject]$Owner)

    if ($null -eq $Owner) {
        # Metadata is unreadable or missing: treat as stale wreckage. The
        # atomic move publishes owner.json together with the directory, so a
        # healthy lock always has readable metadata.
        return $true
    }
    $ownerPid = [int]$Owner.owner_pid
    $currentStart = Get-IzoProcessStartText -ProcessId $ownerPid
    if (-not $currentStart) {
        return $true
    }
    if ($currentStart -ne [string]$Owner.owner_process_start_utc) {
        # A different process now occupies the recorded PID (PID reuse).
        return $true
    }
    return $false
}

function Lock-IzoRepositoryOperation {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Kind,
        [string]$OperationCommand = "",
        [int]$OwnerProcessId = $PID,
        [ValidateSet("worktree", "common-repository")]
        [string]$StorageScope = "worktree"
    )

    $resolvedRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
    $lockPath = Get-IzoRepositoryLockPath -RepoRoot $resolvedRoot -Kind $Kind -StorageScope $StorageScope
    $lockRoot = Split-Path -Parent $lockPath
    $tokenVariable = Get-IzoRepositoryLockTokenVariable -Kind $Kind
    New-Item -ItemType Directory -Force -Path $lockRoot | Out-Null

    $environmentToken = [Environment]::GetEnvironmentVariable($tokenVariable)
    if ($environmentToken -and $environmentToken.Trim() -and (Test-Path -LiteralPath $lockPath)) {
        $existingOwner = Get-IzoRepositoryLockOwner -LockPath $lockPath
        if ($null -ne $existingOwner -and [string]$existingOwner.reentry_token -eq $environmentToken.Trim()) {
            return [pscustomobject]@{
                Kind = $Kind
                Path = $lockPath
                Token = $environmentToken.Trim()
                TokenVariable = $tokenVariable
                Reentrant = $true
            }
        }
    }

    $ownerStart = Get-IzoProcessStartText -ProcessId $OwnerProcessId
    if (-not $ownerStart) {
        throw "Repository operation lock owner process $OwnerProcessId could not be resolved."
    }

    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $reentryToken = [guid]::NewGuid().ToString("N")
        $metadata = [ordered]@{
            lock_version = 1
            kind = $Kind
            operation_id = [guid]::NewGuid().ToString("N")
            owner_pid = $OwnerProcessId
            owner_process_start_utc = $ownerStart
            command = $OperationCommand
            acquired_at_utc = (Get-Date).ToUniversalTime().ToString("o")
            reentry_token = $reentryToken
        }
        $stagingPath = Join-Path $lockRoot (".staging-" + [guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $stagingPath | Out-Null
        $metadata | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stagingPath "owner.json") -Encoding UTF8
        try {
            [System.IO.Directory]::Move($stagingPath, $lockPath)
            return [pscustomobject]@{
                Kind = $Kind
                Path = $lockPath
                Token = $reentryToken
                TokenVariable = $tokenVariable
                Reentrant = $false
            }
        } catch [System.IO.IOException] {
            Remove-Item -LiteralPath $stagingPath -Recurse -Force -ErrorAction SilentlyContinue
            $owner = Get-IzoRepositoryLockOwner -LockPath $lockPath
            if (Test-IzoRepositoryLockStale -Owner $owner) {
                Remove-Item -LiteralPath $lockPath -Recurse -Force -ErrorAction SilentlyContinue
                continue
            }
            $ownerCommand = if ($null -ne $owner) { [string]$owner.command } else { "unknown" }
            $ownerId = if ($null -ne $owner) { [string]$owner.operation_id } else { "unknown" }
            $ownerPidText = if ($null -ne $owner) { [string]$owner.owner_pid } else { "unknown" }
            $ownerSince = if ($null -ne $owner) { [string]$owner.acquired_at_utc } else { "unknown" }
            throw ("REPOSITORY_OPERATION_LOCK_BUSY kind=$Kind owner_pid=$ownerPidText operation=$ownerId " +
                "command='$ownerCommand' acquired_at=$ownerSince. Another agent owns this operation; " +
                "do not start a second release/verification. Wait for it to finish or investigate the owner PID.")
        }
    }
    throw "Repository operation lock '$Kind' could not be acquired after stale recovery attempts."
}

function Unlock-IzoRepositoryOperation {
    param([pscustomobject]$Handle)

    if ($null -eq $Handle -or $Handle.Reentrant) {
        return
    }
    $owner = Get-IzoRepositoryLockOwner -LockPath $Handle.Path
    if ($null -eq $owner -or [string]$owner.reentry_token -ne $Handle.Token) {
        # The lock was stale-recovered by another process; never delete an
        # owner record that is not ours.
        return
    }
    Remove-Item -LiteralPath $Handle.Path -Recurse -Force -ErrorAction SilentlyContinue
}

if ($Action) {
    $ErrorActionPreference = "Stop"
    if (-not $RepoRoot.Trim()) {
        $RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
    }
    if (-not $Kind.Trim()) {
        throw "-Kind is required for repository operation lock actions."
    }
    switch ($Action) {
        "acquire" {
            # Batch launchers invoke this CLI in a transient PowerShell; the
            # durable owner is the launcher shell itself, so record the parent
            # process (the cmd.exe running the .bat) as the lock owner.
            $ownerPid = $OwnerProcessId
            if ($ownerPid -le 0) {
                $parentPid = [int](Get-CimInstance Win32_Process -Filter "ProcessId=$PID").ParentProcessId
                $ownerPid = if ($parentPid -gt 0 -and (Get-IzoProcessStartText -ProcessId $parentPid)) { $parentPid } else { $PID }
            }
            $handle = Lock-IzoRepositoryOperation `
                -RepoRoot $RepoRoot `
                -Kind $Kind `
                -OperationCommand $Command `
                -OwnerProcessId $ownerPid `
                -StorageScope $StorageScope
            if ($TokenOutFile.Trim()) {
                Set-Content -LiteralPath $TokenOutFile -Value $handle.Token -Encoding ASCII -NoNewline
            }
            Write-Host "REPOSITORY_OPERATION_LOCK_ACQUIRED kind=$Kind owner_pid=$ownerPid"
        }
        "release" {
            if (-not $Token.Trim()) {
                throw "-Token is required to release a repository operation lock."
            }
            $lockPath = Get-IzoRepositoryLockPath -RepoRoot (Resolve-Path -LiteralPath $RepoRoot).Path -Kind $Kind -StorageScope $StorageScope
            $owner = Get-IzoRepositoryLockOwner -LockPath $lockPath
            if ($null -eq $owner) {
                Write-Host "REPOSITORY_OPERATION_LOCK_ALREADY_RELEASED kind=$Kind"
            } elseif ([string]$owner.reentry_token -ne $Token.Trim()) {
                throw "Repository operation lock '$Kind' is owned by another operation; refusing release."
            } else {
                Remove-Item -LiteralPath $lockPath -Recurse -Force
                Write-Host "REPOSITORY_OPERATION_LOCK_RELEASED kind=$Kind"
            }
        }
        "status" {
            $lockPath = Get-IzoRepositoryLockPath -RepoRoot (Resolve-Path -LiteralPath $RepoRoot).Path -Kind $Kind -StorageScope $StorageScope
            $owner = Get-IzoRepositoryLockOwner -LockPath $lockPath
            if ($null -eq $owner) {
                Write-Host "REPOSITORY_OPERATION_LOCK_FREE kind=$Kind"
            } else {
                $stale = Test-IzoRepositoryLockStale -Owner $owner
                Write-Host "REPOSITORY_OPERATION_LOCK_HELD kind=$Kind owner_pid=$($owner.owner_pid) stale=$stale acquired_at=$($owner.acquired_at_utc)"
            }
        }
    }
}
