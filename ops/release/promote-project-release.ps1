[CmdletBinding()]
param(
    [string]$MarkerPath = 'C:\IZO_ASA\runtime\pending-release-promotion.json'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$backendXml = 'C:\IZO_ASA\runtime\services\backend\IZOBackend.xml'
$backendExe = 'C:\IZO_ASA\runtime\services\backend\IZOBackend.exe'
$caddyFile = 'C:\IZO_ASA\config\Caddyfile'
$caddyExe = 'C:\IZO_ASA\runtime\services\caddy\IZOCaddy.exe'
$operationsPath = 'C:\IZO_ASA\config\backup-operations.json'
$promotionStatusPath = 'C:\IZO_ASA\health\promotion-current.json'
$updateStatusPath = 'C:\IZO_ASA\health\update-current.json'
$git = 'C:\Users\admins\AppData\Local\Programs\Git\cmd\git.exe'
$nodeDirectory = 'C:\Users\admins\AppData\Local\Programs\nodejs'

function Get-ServiceEnvironmentNode {
    param([xml]$Document, [string]$Name)
    return $Document.service.env |
        Where-Object { [string]$_.name -eq $Name } |
        Select-Object -First 1
}

function Set-ServiceEnvironmentValue {
    param([xml]$Document, [string]$Name, [string]$Value)
    $node = Get-ServiceEnvironmentNode -Document $Document -Name $Name
    if ($null -eq $node) {
        $node = $Document.CreateElement('env')
        $node.SetAttribute('name', $Name)
        $node.SetAttribute('value', $Value)
        $null = $Document.service.AppendChild($node)
        return
    }
    $node.SetAttribute('value', $Value)
}

function Write-PromotionStatus {
    param(
        [bool]$Ok,
        [string]$Stage,
        [string]$Message,
        [string]$PreviousSha,
        [string]$NewSha,
        [string]$RollbackPath,
        [string]$ReleaseId = '',
        [string]$ManifestPath = ''
    )
    [ordered]@{
        Timestamp = (Get-Date).ToString('o')
        Ok = $Ok
        Stage = $Stage
        Message = $Message
        PreviousSha = $PreviousSha
        NewSha = $NewSha
        ReleaseId = $ReleaseId
        ReleaseManifest = $ManifestPath
        RollbackPath = $RollbackPath
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $promotionStatusPath -Encoding UTF8
}

$promotionMutex = [System.Threading.Mutex]::new(
    $false,
    'Global\IZO_ASA_ProjectReleasePromotion'
)
$promotionLockAcquired = $false
try {
    $promotionLockAcquired = $promotionMutex.WaitOne(0)
} catch [System.Threading.AbandonedMutexException] {
    $promotionLockAcquired = $true
}
if (-not $promotionLockAcquired) {
    $promotionMutex.Dispose()
    throw 'Another project release promotion is already running.'
}

try {
if (-not (Test-Path -LiteralPath $MarkerPath)) {
    throw "Promotion marker is missing: $MarkerPath"
}

$marker = Get-Content -LiteralPath $MarkerPath -Raw -Encoding UTF8 | ConvertFrom-Json
$newSha = [string]$marker.NewSha
if ($newSha -notmatch '^[0-9a-f]{40}$') {
    throw 'Promotion marker contains an invalid commit SHA.'
}

$newRelease = if ([string]$marker.CandidatePath) {
    [IO.Path]::GetFullPath([string]$marker.CandidatePath)
} else {
    "C:\IZO_ASA\releases\$newSha"
}
$expectedRelease = [IO.Path]::GetFullPath("C:\IZO_ASA\releases\$newSha")
if (-not $newRelease.Equals($expectedRelease, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Promotion candidate path does not match the requested commit.'
}

$currentXml = [xml](Get-Content -LiteralPath $backendXml -Raw -Encoding UTF8)
$gitNode = Get-ServiceEnvironmentNode -Document $currentXml -Name 'GIT_COMMIT'
$databaseNode = Get-ServiceEnvironmentNode -Document $currentXml -Name 'DATABASE_URL'
$oldSha = [string]$gitNode.value
if ($oldSha -notmatch '^[0-9a-f]{40}$') {
    throw 'The active service commit is invalid.'
}
if ($oldSha -eq $newSha) {
    Remove-Item -LiteralPath $MarkerPath -Force
    exit 0
}

$oldRelease = "C:\IZO_ASA\releases\$oldSha"
$short = $newSha.Substring(0, 7)
$databaseUrl = [string]$databaseNode.value
$database = $databaseUrl -replace '^sqlite:///', ''
$database = $database -replace '/', '\'
$database = [IO.Path]::GetFullPath($database)
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$rollback = "C:\IZO_ASA\rollback\$stamp-before-$short"
$releaseId = ''
$manifestPath = ''
$frontendRoot = Join-Path $newRelease 'frontend\dist'
$hotBackupTool = Join-Path $newRelease 'tools\sqlite_hot_backup.py'

try {
    foreach ($required in @(
        "$newRelease\backend\.venv\Scripts\python.exe",
        "$newRelease\backend\main.py",
        "$newRelease\frontend\dist\index.html",
        $hotBackupTool,
        $backendXml, $backendExe, $caddyFile, $caddyExe, $database, $git
    )) {
        if (-not (Test-Path -LiteralPath $required)) {
            throw "Required promotion input is missing: $required"
        }
    }
    if (-not $database.StartsWith('C:\IZO_ASA\', [StringComparison]::OrdinalIgnoreCase) -and
        -not $database.StartsWith('F:\IZO_ASA\', [StringComparison]::OrdinalIgnoreCase) -and
        -not $database.StartsWith('F:\IZO_ASA_StandbyData\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to snapshot a database outside the IZO_ASA data roots: $database"
    }

    # Newer project revisions use an immutable release manifest. Build that
    # artifact before any service is stopped, and keep legacy revisions working.
    $manifestBuilder = Join-Path $newRelease 'tools\build_release_manifest.py'
    if (Test-Path -LiteralPath $manifestBuilder) {
        $head = ([string](& $git -C $newRelease rev-parse HEAD)).Trim()
        if ($LASTEXITCODE -ne 0 -or $head -ne $newSha) {
            throw 'Candidate checkout does not match the requested commit.'
        }
        if (@(& $git -C $newRelease status --porcelain).Count -gt 0) {
            throw 'Candidate checkout is dirty before immutable artifact creation.'
        }
        $commitUnix = [long](([string](& $git -C $newRelease show -s --format=%ct $newSha)).Trim())
        if ($LASTEXITCODE -ne 0 -or $commitUnix -le 0) {
            throw 'Unable to resolve the candidate commit timestamp.'
        }
        $releaseId = $newSha.Substring(0, 12) + '-' +
            [DateTimeOffset]::FromUnixTimeSeconds($commitUnix).UtcDateTime.ToString('yyyyMMddHHmmss')
        $runtimeFrontendRoot = Join-Path $newRelease '.runtime\releases\frontend'
        $frontendRoot = Join-Path $runtimeFrontendRoot $releaseId
        $manifestPath = Join-Path $frontendRoot 'release-manifest.json'

        if (-not (Test-Path -LiteralPath $manifestPath)) {
            New-Item -ItemType Directory -Force -Path $runtimeFrontendRoot | Out-Null
            $temporaryFrontend = Join-Path $runtimeFrontendRoot ('.building-' + $releaseId + '-' + $PID)
            if (Test-Path -LiteralPath $temporaryFrontend) {
                Remove-Item -LiteralPath $temporaryFrontend -Recurse -Force
            }
            New-Item -ItemType Directory -Force -Path $temporaryFrontend | Out-Null
            Copy-Item -Path (Join-Path $newRelease 'frontend\dist\*') `
                -Destination $temporaryFrontend -Recurse -Force

            $oldPath = $env:PATH
            try {
                $env:PATH = (Split-Path $git -Parent) + ';' + $nodeDirectory + ';' + $oldPath
                & "$newRelease\backend\.venv\Scripts\python.exe" $manifestBuilder `
                    --root $newRelease `
                    --release-path $temporaryFrontend `
                    --release-id $releaseId `
                    --git-sha $newSha `
                    --built-at ([DateTimeOffset]::FromUnixTimeSeconds($commitUnix).ToString('o'))
                if ($LASTEXITCODE -ne 0) {
                    throw "Release manifest build failed with exit code $LASTEXITCODE."
                }
            } finally {
                $env:PATH = $oldPath
            }
            if (Test-Path -LiteralPath $frontendRoot) {
                throw "Immutable frontend target already exists without a manifest: $frontendRoot"
            }
            Move-Item -LiteralPath $temporaryFrontend -Destination $frontendRoot
        }

        $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([string]$manifest.release_id -ne $releaseId -or
            [string]$manifest.git_sha -ne $newSha -or
            $manifest.dirty -ne $false) {
            throw 'Generated release manifest identity is invalid.'
        }
    }
} catch {
    $failure = $_.Exception.Message
    Write-PromotionStatus -Ok $false -Stage 'preparation_failed' -Message $failure `
        -PreviousSha $oldSha -NewSha $newSha -RollbackPath $rollback `
        -ReleaseId $releaseId -ManifestPath $manifestPath
    if (Test-Path -LiteralPath $updateStatusPath) {
        $update = Get-Content -LiteralPath $updateStatusPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $update.Status = 'PROMOTION_FAILED'
        $update.Message = 'Automatic release preparation failed; inspect promotion-current.json.'
        $update.Error = $failure
        $update | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $updateStatusPath -Encoding UTF8
    }
    Remove-Item -LiteralPath $MarkerPath -Force -ErrorAction SilentlyContinue
    exit 1
}

New-Item -ItemType Directory -Force -Path $rollback | Out-Null
Copy-Item -LiteralPath $backendXml -Destination (Join-Path $rollback 'IZOBackend.xml') -Force
Copy-Item -LiteralPath $caddyFile -Destination (Join-Path $rollback 'Caddyfile') -Force
if (Test-Path -LiteralPath $operationsPath) {
    Copy-Item -LiteralPath $operationsPath -Destination (Join-Path $rollback 'backup-operations.json') -Force
}

try {
    $rollbackDatabase = Join-Path $rollback 'database.sqlite3'
    Write-PromotionStatus -Ok $false -Stage 'backup' `
        -Message 'Creating a consistent online rollback snapshot before the service switch.' `
        -PreviousSha $oldSha -NewSha $newSha -RollbackPath $rollback `
        -ReleaseId $releaseId -ManifestPath $manifestPath
    & "$newRelease\backend\.venv\Scripts\python.exe" $hotBackupTool `
        --source $database --destination $rollbackDatabase
    if ($LASTEXITCODE -ne 0) {
        throw "Online database backup failed with exit code $LASTEXITCODE."
    }

    Write-PromotionStatus -Ok $false -Stage 'stopping' `
        -Message 'Online rollback snapshot is complete; switching the backend release.' `
        -PreviousSha $oldSha -NewSha $newSha -RollbackPath $rollback `
        -ReleaseId $releaseId -ManifestPath $manifestPath
    & $backendExe stop
    if ($LASTEXITCODE -ne 0) { throw "Backend stop failed with exit code $LASTEXITCODE." }
    & $caddyExe stop
    if ($LASTEXITCODE -ne 0) { throw "Caddy stop failed with exit code $LASTEXITCODE." }

    $xml = [xml](Get-Content -LiteralPath $backendXml -Raw -Encoding UTF8)
    $xml.service.executable = "$newRelease\backend\.venv\Scripts\python.exe"
    $xml.service.workingdirectory = "$newRelease\backend"
    Set-ServiceEnvironmentValue -Document $xml -Name 'GIT_COMMIT' -Value $newSha
    Set-ServiceEnvironmentValue -Document $xml -Name 'APP_BUILD' `
        -Value $(if ($releaseId) { $releaseId } else { "local-$short" })
    Set-ServiceEnvironmentValue -Document $xml -Name 'FRONTEND_BUILD_LABEL' `
        -Value $(if ($releaseId) { $releaseId } else { "local-$short" })
    Set-ServiceEnvironmentValue -Document $xml -Name 'IZO_SECRET_DIR' -Value 'C:\IZO_ASA\secrets'
    Set-ServiceEnvironmentValue -Document $xml -Name 'IZO_RELEASE_MANIFEST' -Value $manifestPath
    $xml.Save($backendXml)

    $caddy = Get-Content -LiteralPath $caddyFile -Raw -Encoding UTF8
    $frontendRootMatch = [regex]::Matches(
        $caddy,
        '(?m)^\s*root \* (?<path>C:\\IZO_ASA\\releases\\[^\r\n]+\\frontend\\[^\r\n]+)\s*$'
    )
    if ($frontendRootMatch.Count -ne 1) {
        throw "Expected exactly one active frontend root in Caddyfile, found $($frontendRootMatch.Count)."
    }
    $oldFrontendRoot = [string]$frontendRootMatch[0].Groups['path'].Value
    $caddy = $caddy.Replace($oldFrontendRoot, $frontendRoot)
    $caddy | Set-Content -LiteralPath $caddyFile -Encoding UTF8

    if (Test-Path -LiteralPath $operationsPath) {
        $operations = Get-Content -LiteralPath $operationsPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $operations.active_release = $newRelease
        $operations.python = "$newRelease\backend\.venv\Scripts\python.exe"
        $operations | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $operationsPath -Encoding UTF8
    }

    & $backendExe start
    if ($LASTEXITCODE -ne 0) { throw "Backend start failed with exit code $LASTEXITCODE." }
    & $caddyExe start
    if ($LASTEXITCODE -ne 0) { throw "Caddy start failed with exit code $LASTEXITCODE." }

    $backendReady = $false
    $identityReady = $false
    $frontendReady = $false
    for ($i = 0; $i -lt 90; $i++) {
        Start-Sleep -Seconds 1
        try {
            $healthResponse = Invoke-WebRequest 'http://127.0.0.1:8000/api/health' -UseBasicParsing -TimeoutSec 3
            $healthBody = $healthResponse.Content | ConvertFrom-Json
            $ready = if ($healthBody.PSObject.Properties.Name -contains 'ready') {
                [bool]$healthBody.ready
            } elseif ($healthBody.PSObject.Properties.Name -contains 'database') {
                [bool]$healthBody.database.ready
            } else {
                [bool]$healthBody.ok
            }
            $backendReady = $healthResponse.StatusCode -eq 200 -and [bool]$healthBody.ok -and $ready
            if ($releaseId) {
                $versionResponse = Invoke-WebRequest 'http://127.0.0.1:8000/api/version' -UseBasicParsing -TimeoutSec 3
                $versionBody = $versionResponse.Content | ConvertFrom-Json
                $identityReady = (
                    [string]$healthBody.release_id -eq $releaseId -and
                    [string]$versionBody.release_id -eq $releaseId -and
                    [string]$versionBody.backend_commit -eq $newSha -and
                    [string]$versionBody.frontend_build -eq $releaseId
                )
            } else {
                $identityReady = [string]$healthBody.version -eq "local-$short"
            }
        } catch {}
        try {
            $frontendResponse = Invoke-WebRequest 'http://127.0.0.1:5173/' -UseBasicParsing -TimeoutSec 3
            $frontendReady = $frontendResponse.StatusCode -eq 200
        } catch {}
        if ($backendReady -and $identityReady -and $frontendReady) { break }
    }
    if (-not $backendReady) { throw 'New backend did not become ready.' }
    if (-not $identityReady) { throw 'New backend release identity did not match the installed commit.' }
    if (-not $frontendReady) { throw 'New frontend did not become healthy on port 5173.' }

    if (Test-Path -LiteralPath $updateStatusPath) {
        $update = Get-Content -LiteralPath $updateStatusPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $update.Status = 'INSTALLED'
        $update.Message = 'The verified GitHub release was installed automatically and passed post-promotion health checks.'
        $update.ActiveSha = $newSha
        $update.AutomaticPromotion = $true
        $update.Error = ''
        if ($update.PSObject.Properties.Name -contains 'ActiveReleaseId') {
            $update.ActiveReleaseId = $releaseId
        } else {
            $update | Add-Member -NotePropertyName ActiveReleaseId -NotePropertyValue $releaseId
        }
        $update | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $updateStatusPath -Encoding UTF8
    }
    Remove-Item -LiteralPath $MarkerPath -Force -ErrorAction SilentlyContinue
    Write-PromotionStatus -Ok $true -Stage 'complete' `
        -Message 'Release installed and verified on ports 8000 and 5173.' `
        -PreviousSha $oldSha -NewSha $newSha -RollbackPath $rollback `
        -ReleaseId $releaseId -ManifestPath $manifestPath
    exit 0
} catch {
    $failure = $_.Exception.Message
    try {
        & $backendExe stop 2>$null
        & $caddyExe stop 2>$null
        Copy-Item -LiteralPath (Join-Path $rollback 'IZOBackend.xml') -Destination $backendXml -Force
        Copy-Item -LiteralPath (Join-Path $rollback 'Caddyfile') -Destination $caddyFile -Force
        # Migrations are additive. Keep the live database in place during an
        # automatic code/config rollback; the immutable online snapshot is for
        # an explicit, rehearsed operator recovery only.
        if (Test-Path -LiteralPath (Join-Path $rollback 'backup-operations.json')) {
            Copy-Item -LiteralPath (Join-Path $rollback 'backup-operations.json') -Destination $operationsPath -Force
        }
        & $backendExe start
        & $caddyExe start
        Write-PromotionStatus -Ok $false -Stage 'rolled_back' `
            -Message "Promotion failed and the previous release was restored: $failure" `
            -PreviousSha $oldSha -NewSha $newSha -RollbackPath $rollback `
            -ReleaseId $releaseId -ManifestPath $manifestPath
    } catch {
        Write-PromotionStatus -Ok $false -Stage 'rollback_failed' `
            -Message "Promotion failed: $failure. Rollback also failed: $($_.Exception.Message)" `
            -PreviousSha $oldSha -NewSha $newSha -RollbackPath $rollback `
            -ReleaseId $releaseId -ManifestPath $manifestPath
    }
    if (Test-Path -LiteralPath $updateStatusPath) {
        $update = Get-Content -LiteralPath $updateStatusPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $update.Status = 'PROMOTION_FAILED'
        $update.Message = 'Automatic release installation failed; inspect promotion-current.json.'
        $update.Error = $failure
        $update | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $updateStatusPath -Encoding UTF8
    }
    Remove-Item -LiteralPath $MarkerPath -Force -ErrorAction SilentlyContinue
    exit 1
}
} finally {
    foreach ($serviceName in @('IZOBackend', 'IZOCaddy')) {
        try {
            $service = Get-Service -Name $serviceName -ErrorAction Stop
            if ($service.Status -ne 'Running') {
                Start-Service -Name $serviceName -ErrorAction Stop
                $service.WaitForStatus('Running', [TimeSpan]::FromSeconds(30))
            }
        } catch {}
    }
    if ($promotionLockAcquired) {
        try { $promotionMutex.ReleaseMutex() } catch {}
    }
    $promotionMutex.Dispose()
}
