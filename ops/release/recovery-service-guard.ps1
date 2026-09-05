# Dot-source after tools/repository-operation-lock.ps1. This guard belongs to
# the existing production-release owner; it is not another locking mechanism.
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'service-recovery-config.ps1')

function Assert-IzoRecoveryAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Recovery service guard requires an elevated Windows Administrator process.'
    }
}

function Get-IzoRecoveryService {
    $service = Get-CimInstance Win32_Service -Filter "Name='IZOBackend'" -ErrorAction Stop
    $executable = ([string]$service.PathName).Trim().Trim('"')
    if (-not [string]::Equals($executable,
        'C:\IZO_ASA\runtime\services\backend\IZOBackend.exe', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Recovery service is not the installed IZOBackend executable.'
    }
    return $service
}

function Assert-IzoRecoveryOwner {
    param([string]$RepoRoot, [object]$Record)

    $lockPath = Get-IzoRepositoryLockPath -RepoRoot $RepoRoot -Kind 'production-release'
    $owner = Get-IzoRepositoryLockOwner -LockPath $lockPath
    if ($null -eq $owner -or (Test-IzoRepositoryLockStale -Owner $owner) -or
        [string]$Record.OperationId -ne [string]$owner.operation_id -or
        [int]$Record.OwnerPid -ne [int]$owner.owner_pid -or
        [string]$Record.OwnerStart -ne [string]$owner.owner_process_start_utc) {
        throw 'Recovery maintenance does not belong to the live production-release owner.'
    }
}

function Assert-IzoRecoveryMaintenance {
    param(
        [string]$RepoRoot,
        [string]$ExpectedSha,
        [string]$MaintenancePath = 'C:\IZO_ASA\runtime\project-release-maintenance.flag',
        [switch]$RequireStopped
    )

    $record = Get-Content -LiteralPath $MaintenancePath -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json
    if ($null -eq $record.PSObject.Properties['Schema'] -or
        [string]$record.Schema -ne 'izo.recovery-service-guard.v1' -or
        [string]$record.Sha -ne $ExpectedSha -or
        [string]$record.RepoRoot -ne $RepoRoot -or
        [string]$record.OriginalStartup -ne 'Automatic' -or
        $null -eq $record.PSObject.Properties['OriginalDelayedAutoStart'] -or
        $record.OriginalDelayedAutoStart -isnot [bool]) {
        throw 'Recovery maintenance record has an unexpected identity.'
    }
    Assert-IzoRecoveryOwner -RepoRoot $RepoRoot -Record $record
    if ($RequireStopped) {
        $service = Get-IzoRecoveryService
        if ([string]$service.StartMode -ne 'Disabled' -or [string]$service.State -ne 'Stopped' -or
            [int]$service.ProcessId -ne 0 -or
            @(Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue).Count -ne 0) {
            throw 'Recovery requires Disabled startup, Stopped IZOBackend, PID zero and closed port 8000.'
        }
    }
    return $record
}

function New-IzoRecoveryServiceGuard {
    param(
        [string]$RepoRoot, [string]$ExpectedSha, [string]$JournalPath,
        [string]$MaintenancePath = 'C:\IZO_ASA\runtime\project-release-maintenance.flag'
    )

    $root = (Resolve-Path -LiteralPath $RepoRoot).Path
    Assert-IzoRecoveryAdministrator
    $owner = Get-IzoRepositoryLockOwner -LockPath (Get-IzoRepositoryLockPath -RepoRoot $root -Kind 'production-release')
    if ($null -eq $owner -or [int]$owner.owner_pid -ne $PID -or (Test-IzoRepositoryLockStale -Owner $owner)) {
        throw 'Only the live production-release owner may create recovery maintenance.'
    }
    $service = Get-IzoRecoveryService
    if ([string]$service.StartMode -ne 'Auto' -or $service.DelayedAutoStart -isnot [bool]) {
        throw 'Recovery requires an Automatic service with a known delayed-start setting.'
    }
    $delays = @(Get-IzoServiceRecoveryDelays -ServiceName 'IZOBackend')
    if ($delays.Count -eq 0) { throw 'SCM recovery actions are missing; no service changed.' }
    $drainSeconds = [math]::Ceiling((($delays | Measure-Object -Maximum).Maximum) / 1000) + 10
    if ($drainSeconds -gt 600) { throw 'SCM recovery delay exceeds the bounded recovery window.' }
    $guard = [pscustomobject]@{
        Schema = 'izo.recovery-service-guard.v1'
        OperationId = [string]$owner.operation_id
        OwnerPid = $PID
        OwnerStart = [string]$owner.owner_process_start_utc
        RepoRoot = $root
        Sha = $ExpectedSha
        OriginalStartup = 'Automatic'
        OriginalDelayedAutoStart = [bool]$service.DelayedAutoStart
        DrainSeconds = $drainSeconds
        MaintenancePath = $MaintenancePath
        JournalPath = $JournalPath
        DisabledAtUtc = ''
        StartupRestored = $false
        PromotionHandedOff = $false
    }
    if (Test-Path -LiteralPath $JournalPath) { throw 'Recovery guard journal already exists.' }
    $stream = [IO.File]::Open($MaintenancePath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes(($guard | ConvertTo-Json))
        $stream.Write($bytes, 0, $bytes.Length)
    } finally { $stream.Dispose() }
    try { $guard | ConvertTo-Json | Set-Content -LiteralPath $JournalPath -Encoding UTF8 -ErrorAction Stop }
    catch {
        Remove-Item -LiteralPath $MaintenancePath -ErrorAction Stop
        throw
    }
    return $guard
}

function Suspend-IzoRecoveryBackend {
    param([object]$Guard)

    $null = Assert-IzoRecoveryMaintenance -RepoRoot $Guard.RepoRoot -ExpectedSha $Guard.Sha -MaintenancePath $Guard.MaintenancePath
    $null = Get-IzoRecoveryService
    # Disable before stopping: queued SCM failure actions ignore the health
    # check's maintenance flag and can otherwise restart the service later.
    Set-Service -Name 'IZOBackend' -StartupType Disabled -ErrorAction Stop
    $Guard.DisabledAtUtc = [datetime]::UtcNow.ToString('o')
    $Guard | ConvertTo-Json | Set-Content -LiteralPath $Guard.JournalPath -Encoding UTF8 -ErrorAction Stop
    $service = Get-Service -Name 'IZOBackend' -ErrorAction Stop
    if ($service.Status -ne 'Stopped') { Stop-Service -Name 'IZOBackend' -Force -ErrorAction Stop }
    $deadline = [datetime]::UtcNow.AddSeconds(90)
    do {
        $snapshot = Get-IzoRecoveryService
        if ($snapshot.StartMode -ne 'Disabled') { throw 'Recovery lost the Disabled startup hold.' }
        if ($snapshot.State -eq 'Stopped' -and [int]$snapshot.ProcessId -eq 0 -and
            @(Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue).Count -eq 0) {
            Write-Host 'RECOVERY_SERVICE_HELD startup=Disabled state=Stopped pid=0 port8000=closed'
            return
        }
        Start-Sleep -Milliseconds 500
    } while ([datetime]::UtcNow -lt $deadline)
    throw 'Recovery backend did not reach Stopped/PID-zero/port-closed state.'
}

function Restore-IzoRecoveryStartup {
    param([object]$Guard, [switch]$ForPromotion)

    Assert-IzoRecoveryOwner -RepoRoot $Guard.RepoRoot -Record $Guard
    $service = Get-IzoRecoveryService
    if ($service.StartMode -notin @('Auto', 'Disabled')) { throw 'Service startup changed outside this recovery operation.' }
    if ($ForPromotion) {
        $null = Assert-IzoRecoveryMaintenance -RepoRoot $Guard.RepoRoot -ExpectedSha $Guard.Sha -MaintenancePath $Guard.MaintenancePath -RequireStopped
        # Drain all already-queued SCM restart attempts while starts are disabled.
        $remaining = $Guard.DrainSeconds - ([datetime]::UtcNow - [datetime]::Parse($Guard.DisabledAtUtc).ToUniversalTime()).TotalSeconds
        while ($remaining -gt 0) {
            Start-Sleep -Seconds ([int][math]::Min(5, [math]::Ceiling($remaining)))
            $remaining = $Guard.DrainSeconds - ([datetime]::UtcNow - [datetime]::Parse($Guard.DisabledAtUtc).ToUniversalTime()).TotalSeconds
        }
    }
    if ($service.StartMode -eq 'Disabled' -or
        [bool]$service.DelayedAutoStart -ne $Guard.OriginalDelayedAutoStart) {
        # Windows PowerShell 5.1 Set-Service cannot express delayed Automatic.
        $startMode = if ($Guard.OriginalDelayedAutoStart) { 'delayed-auto' } else { 'auto' }
        $null = & sc.exe config IZOBackend start= $startMode
        if ($LASTEXITCODE -ne 0) { throw 'Original Automatic startup restoration failed.' }
    }
    $restored = Get-IzoRecoveryService
    if ($restored.StartMode -ne 'Auto' -or [bool]$restored.DelayedAutoStart -ne $Guard.OriginalDelayedAutoStart) {
        throw 'Original Automatic/delayed startup restoration was not confirmed.'
    }
    $Guard.StartupRestored = $true
    if ($ForPromotion) { $Guard.PromotionHandedOff = $true }
    $Guard | ConvertTo-Json | Set-Content -LiteralPath $Guard.JournalPath -Encoding UTF8 -ErrorAction Stop
    Write-Host "RECOVERY_STARTUP_RESTORED startup=Automatic delayed=$($Guard.OriginalDelayedAutoStart) promotionHandoff=$ForPromotion"
}

function Close-IzoRecoveryServiceGuard {
    param([object]$Guard)

    if ($null -eq $Guard) { return }
    # Restore even if Suspend threw immediately after Set-Service.
    Restore-IzoRecoveryStartup -Guard $Guard
    if (Test-Path -LiteralPath $Guard.MaintenancePath) {
        $record = Get-Content -LiteralPath $Guard.MaintenancePath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($null -eq $record.PSObject.Properties['Schema'] -or
            [string]$record.Schema -ne $Guard.Schema -or [string]$record.OperationId -ne $Guard.OperationId) {
            throw 'Maintenance ownership changed; preserve its flag for operator diagnosis.'
        }
        Remove-Item -LiteralPath $Guard.MaintenancePath -ErrorAction Stop
    }
    Write-Host 'RECOVERY_GUARD_CLOSED startup=Automatic'
}
