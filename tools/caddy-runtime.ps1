function Get-IzoCaddySha256 {
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

function ConvertTo-IzoCaddyPath {
    param([string]$Path)

    return ([IO.Path]::GetFullPath($Path) -replace "\\", "/")
}

function Get-IzoCaddyRuntime {
    param(
        [string]$RepoRoot,
        [switch]$RequireInstalled
    )

    $root = (Resolve-Path -LiteralPath $RepoRoot).Path
    $specPath = Join-Path $root "ops\caddy\runtime.json"
    $configPath = Join-Path $root "ops\caddy\Caddyfile"
    if (-not (Test-Path -LiteralPath $specPath -PathType Leaf) -or -not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        throw "Pinned Caddy runtime files are incomplete."
    }
    $spec = Get-Content -LiteralPath $specPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $executablePath = [IO.Path]::GetFullPath((Join-Path $root ([string]$spec.install_relative_path)))
    $runtime = [pscustomobject]@{
        Root = $root
        SpecPath = $specPath
        ConfigPath = $configPath
        ExecutablePath = $executablePath
        Version = [string]$spec.version
        ExecutableSha256 = [string]$spec.executable_sha256
        ProductionPort = [int]$spec.production_port
        CandidatePort = [int]$spec.candidate_port
        ProductionAdminAddress = [string]$spec.production_admin_address
        CandidateAdminAddress = [string]$spec.candidate_admin_address
    }
    if ($RequireInstalled) {
        Assert-IzoCaddyRuntime -Runtime $runtime
    }
    return $runtime
}

function Assert-IzoCaddyRuntime {
    param([pscustomobject]$Runtime)

    if (-not (Test-Path -LiteralPath $Runtime.ExecutablePath -PathType Leaf)) {
        throw "Pinned Caddy executable is missing. Run tools\install-caddy.ps1 first."
    }
    $actualHash = Get-IzoCaddySha256 -Path $Runtime.ExecutablePath
    if ($actualHash -ne $Runtime.ExecutableSha256) {
        throw "Pinned Caddy executable failed its SHA-256 integrity check."
    }
    $actualVersion = [string](@(& $Runtime.ExecutablePath version 2>&1)[0])
    if ($actualVersion -notlike "v$($Runtime.Version) *") {
        throw "Pinned Caddy executable version mismatch: $actualVersion"
    }
}

function Set-IzoCaddyEnvironment {
    param(
        [pscustomobject]$Runtime,
        [string]$ReleasePath,
        [string]$ReleaseId,
        [int]$Port,
        [string]$AdminAddress,
        [ValidateSet("production", "candidate", "validation")]
        [string]$Scope
    )

    $resolvedRelease = (Resolve-Path -LiteralPath $ReleasePath).Path
    if (-not (Test-Path -LiteralPath (Join-Path $resolvedRelease "index.html") -PathType Leaf) -and $Scope -ne "validation") {
        throw "Caddy frontend root has no index.html: $resolvedRelease"
    }
    $safeReleaseId = if ($ReleaseId -match "^[A-Za-z0-9._-]+$") { $ReleaseId } else { "unknown" }
    if ($Scope -eq "production") {
        $logDirectory = Join-Path $Runtime.Root "logs"
        $accessLog = Join-Path $logDirectory "caddy-access.jsonl"
        $runtimeLog = Join-Path $logDirectory "caddy-runtime.jsonl"
    } else {
        $logDirectory = Join-Path $Runtime.Root ".runtime\caddy\$Scope\$safeReleaseId"
        $accessLog = Join-Path $logDirectory "access.jsonl"
        $runtimeLog = Join-Path $logDirectory "runtime.jsonl"
    }
    New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
    $env:IZO_FRONTEND_ROOT = ConvertTo-IzoCaddyPath -Path $resolvedRelease
    $env:IZO_CADDY_PORT = [string]$Port
    $env:IZO_CADDY_ADMIN_ADDRESS = $AdminAddress
    $env:IZO_CADDY_BACKEND_ADDRESS = "127.0.0.1:8000"
    $env:IZO_CADDY_ACCESS_LOG = ConvertTo-IzoCaddyPath -Path $accessLog
    $env:IZO_CADDY_RUNTIME_LOG = ConvertTo-IzoCaddyPath -Path $runtimeLog
    return [pscustomobject]@{
        ReleasePath = $resolvedRelease
        ReleaseId = $ReleaseId
        Port = $Port
        AdminAddress = $AdminAddress
        AccessLog = $accessLog
        RuntimeLog = $runtimeLog
        Scope = $Scope
    }
}

function Invoke-IzoCaddyValidate {
    param([pscustomobject]$Runtime)

    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = @(& $Runtime.ExecutablePath validate --config $Runtime.ConfigPath --adapter caddyfile 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
    if ($exitCode -ne 0) {
        throw "Caddy configuration validation failed: $($output -join [Environment]::NewLine)"
    }
    Write-Host "CADDY_CONFIG_VALID version=$($Runtime.Version) config=$($Runtime.ConfigPath)"
}

function Start-IzoCaddyProcess {
    param(
        [pscustomobject]$Runtime,
        [string]$PidFile
    )

    $arguments = @(
        "run",
        "--config", "`"$($Runtime.ConfigPath)`"",
        "--adapter", "caddyfile",
        "--pidfile", "`"$PidFile`""
    )
    return Start-Process -FilePath $Runtime.ExecutablePath -ArgumentList $arguments -WorkingDirectory $Runtime.Root -WindowStyle Hidden -PassThru
}

function Invoke-IzoCaddyReload {
    param(
        [pscustomobject]$Runtime,
        [string]$AdminAddress
    )

    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = @(& $Runtime.ExecutablePath reload --config $Runtime.ConfigPath --adapter caddyfile --address $AdminAddress 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
    if ($exitCode -ne 0) {
        throw "Caddy graceful reload failed: $($output -join [Environment]::NewLine)"
    }
    Write-Host "CADDY_RELOAD_OK admin=$AdminAddress"
}

function Stop-IzoCaddyProcess {
    param(
        [pscustomobject]$Runtime,
        [string]$AdminAddress,
        [System.Diagnostics.Process]$Process
    )

    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $stopOutput = @(& $Runtime.ExecutablePath stop --address $AdminAddress 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
    if ($exitCode -ne 0) {
        Write-Warning "Caddy graceful stop failed; the verified candidate process will be terminated: $($stopOutput -join ' ')"
    }
    if ($null -ne $Process) {
        try { $Process.WaitForExit(5000) | Out-Null } catch {}
        if (-not $Process.HasExited) {
            Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        }
    }
}

function Wait-IzoFrontendPortFree {
    param([int]$Port, [int]$Attempts = 60)

    for ($attempt = 0; $attempt -lt $Attempts; $attempt++) {
        if (-not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
            return $true
        }
        Start-Sleep -Milliseconds 250
    }
    return $false
}

function Test-IzoCaddyReleaseReady {
    param(
        [int]$Port,
        [string]$ReleaseId,
        [int]$Attempts = 60
    )

    $marker = 'name=' + [char]34 + 'izo-release' + [char]34 + ' content=' + [char]34 + $ReleaseId + [char]34
    for ($attempt = 0; $attempt -lt $Attempts; $attempt++) {
        try {
            $response = Invoke-WebRequest "http://127.0.0.1:$Port/" -Headers @{ Host = "izo.alikinas.ru" } -UseBasicParsing -TimeoutSec 2
            if (
                $response.StatusCode -eq 200 -and
                $response.Content.Contains($marker) -and
                -not [string]$response.Headers["Server"]
            ) {
                return $true
            }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Test-IzoCaddyServiceFallback {
    param(
        [pscustomobject]$Runtime,
        [pscustomobject]$Process
    )

    if ([string]$Process.Name -ine "caddy.exe" -or [int]$Process.ParentProcessId -le 0) {
        return $false
    }
    $service = Get-CimInstance Win32_Service -Filter "Name='IZOCaddy'" -ErrorAction SilentlyContinue
    if (
        $null -eq $service -or
        [string]$service.State -ne "Running" -or
        [int]$service.ProcessId -ne [int]$Process.ParentProcessId
    ) {
        return $false
    }
    $servicePath = [string]$service.PathName
    $wrapperPath = if ($servicePath -match '^"([^"]+)"') { $Matches[1] } else { ($servicePath -split '\s+', 2)[0] }
    if (-not $wrapperPath.Trim()) {
        return $false
    }
    $serviceConfigPath = [IO.Path]::ChangeExtension([IO.Path]::GetFullPath($wrapperPath), ".xml")
    if (-not (Test-Path -LiteralPath $serviceConfigPath -PathType Leaf)) {
        return $false
    }
    try {
        [xml]$serviceConfig = Get-Content -LiteralPath $serviceConfigPath -Raw -Encoding UTF8
        $configuredExecutable = [IO.Path]::GetFullPath([string]$serviceConfig.service.executable)
        $configuredArguments = [string]$serviceConfig.service.arguments
    } catch {
        return $false
    }
    if (
        [string]$serviceConfig.service.id -ne "IZOCaddy" -or
        -not (Test-Path -LiteralPath $configuredExecutable -PathType Leaf) -or
        [IO.Path]::GetFileName($configuredExecutable) -ine "caddy.exe" -or
        (Get-IzoCaddySha256 -Path $configuredExecutable) -ne $Runtime.ExecutableSha256 -or
        $configuredArguments -notmatch '(?i)\brun\b' -or
        $configuredArguments -notmatch '(?i)--config\s+\S+' -or
        $configuredArguments -notmatch '(?i)--adapter\s+caddyfile'
    ) {
        return $false
    }
    return $true
}

function Get-IzoFrontendListenerState {
    param(
        [pscustomobject]$Runtime,
        [int]$Port
    )

    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -eq 0) {
        return [pscustomobject]@{ Kind = "none"; Process = $null; Listener = $null }
    }
    if ($listeners.Count -ne 1) {
        return [pscustomobject]@{ Kind = "multiple"; Process = $null; Listener = $null }
    }
    $listener = $listeners[0]
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return [pscustomobject]@{ Kind = "unknown"; Process = $null; Listener = $listener }
    }
    $commandLine = [string]$process.CommandLine
    $runtimePath = [IO.Path]::GetFullPath($Runtime.ExecutablePath)
    $actualExecutable = [string]$process.ExecutablePath
    $isCaddy = [string]$process.Name -ieq "caddy.exe" -and (
        ($actualExecutable -and [IO.Path]::GetFullPath($actualExecutable) -ieq $runtimePath) -or
        $commandLine.IndexOf($runtimePath, [StringComparison]::OrdinalIgnoreCase) -ge 0
    ) -and $commandLine.IndexOf($Runtime.ConfigPath, [StringComparison]::OrdinalIgnoreCase) -ge 0
    if ($isCaddy) {
        return [pscustomobject]@{ Kind = "caddy"; Process = $process; Listener = $listener }
    }
    if (Test-IzoCaddyServiceFallback -Runtime $Runtime -Process $process) {
        return [pscustomobject]@{ Kind = "caddy"; Process = $process; Listener = $listener }
    }
    $isLegacyVite = [string]$process.Name -ieq "node.exe" -and $commandLine -match "(?i)vite.+preview" -and $commandLine.IndexOf($Runtime.Root, [StringComparison]::OrdinalIgnoreCase) -ge 0
    if ($isLegacyVite) {
        return [pscustomobject]@{ Kind = "legacy-vite"; Process = $process; Listener = $listener }
    }
    return [pscustomobject]@{ Kind = "unknown"; Process = $process; Listener = $listener }
}
