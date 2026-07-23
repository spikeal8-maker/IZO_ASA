[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [switch]$OpenBrowser,
    [switch]$ResetData,
    [switch]$PlanOnly
)

$ErrorActionPreference = "Stop"

function Resolve-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    return [System.IO.Path]::GetFullPath($Path).TrimEnd("\")
}

function Assert-ChildPath {
    param(
        [Parameter(Mandatory = $true)][string]$Parent,
        [Parameter(Mandatory = $true)][string]$Child
    )

    $parentPath = Resolve-FullPath $Parent
    $childPath = Resolve-FullPath $Child
    $prefix = $parentPath + [System.IO.Path]::DirectorySeparatorChar
    if (-not $childPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing a path outside the isolated runtime root: $childPath"
    }
}

function Assert-PortFree {
    param([Parameter(Mandatory = $true)][int]$Port)

    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) {
        $owners = ($listeners | Select-Object -ExpandProperty OwningProcess -Unique) -join ","
        throw "Port $Port is already owned by PID(s) $owners. Stop the owner explicitly; this launcher never kills unknown processes."
    }
}

function Wait-HttpJson {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [int]$Attempts = 60
    )

    $lastError = ""
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            return Invoke-RestMethod -Uri $Uri -Method Get -TimeoutSec 3
        } catch {
            $lastError = $_.Exception.Message
            Start-Sleep -Milliseconds 500
        }
    }
    throw "Timed out waiting for $Uri. Last error: $lastError"
}

function Wait-HttpStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [int]$ExpectedStatus = 200,
        [int]$Attempts = 60
    )

    $lastStatus = 0
    $lastError = ""
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $Uri -Method Get -UseBasicParsing -TimeoutSec 3
            $lastStatus = [int]$response.StatusCode
            if ($lastStatus -eq $ExpectedStatus) {
                return $response
            }
        } catch {
            $lastError = $_.Exception.Message
            if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
                $lastStatus = [int]$_.Exception.Response.StatusCode
            }
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Timed out waiting for $Uri status=$ExpectedStatus. Last status=$lastStatus error=$lastError"
}

function Get-ListenerPid {
    param([Parameter(Mandatory = $true)][int]$Port)

    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -ne 1) {
        throw "Expected one listener on port $Port, found $($listeners.Count)."
    }
    return [int]$listeners[0].OwningProcess
}

function Stop-StartedProcess {
    param([System.Diagnostics.Process]$Process)

    if ($null -ne $Process -and -not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
    }
}

$root = Resolve-FullPath $RepoRoot
$backendRoot = Join-Path $root "backend"
$frontendRoot = Join-Path $root "frontend"
$runtimeRoot = Join-Path $root ".runtime\local-test"
$dataRoot = Join-Path $runtimeRoot "data"
$databasePath = Join-Path $dataRoot "local-test.sqlite3"
$mediaPath = Join-Path $dataRoot "media"
$logRoot = Join-Path $runtimeRoot "logs"
$manifestPath = Join-Path $runtimeRoot "stack.json"
$python = Join-Path $backendRoot ".venv\Scripts\python.exe"
$viteScript = Join-Path $frontendRoot "node_modules\vite\bin\vite.js"

if (-not $env:LOCALAPPDATA) {
    throw "LOCALAPPDATA is required for an isolated secret-store path."
}
$secretRoot = Join-Path $env:LOCALAPPDATA "IZO_ASA\local-test-secrets"

Assert-ChildPath -Parent $root -Child $runtimeRoot
Assert-ChildPath -Parent $runtimeRoot -Child $dataRoot
Assert-ChildPath -Parent $runtimeRoot -Child $databasePath
Assert-ChildPath -Parent $runtimeRoot -Child $mediaPath

Write-Host "LOCAL_TEST_PLAN repo=$root"
Write-Host "LOCAL_TEST_PLAN backend=http://127.0.0.1:$BackendPort frontend=http://127.0.0.1:$FrontendPort"
Write-Host "LOCAL_TEST_PLAN database=$databasePath media=$mediaPath"
Write-Host "LOCAL_TEST_PLAN secrets=$secretRoot providers=disabled-or-fake tunnel=disabled"

if ($PlanOnly) {
    Write-Host "LOCAL_TEST_PLAN_OK"
    exit 0
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python is missing: $python"
}
if (-not (Test-Path -LiteralPath $viteScript -PathType Leaf)) {
    throw "Frontend dependencies are missing. Run npm install in $frontendRoot"
}
$nodeCommand = Get-Command node.exe -ErrorAction Stop
$node = [string]$nodeCommand.Source

Assert-PortFree -Port $BackendPort
Assert-PortFree -Port $FrontendPort

if ($ResetData -and (Test-Path -LiteralPath $dataRoot)) {
    Assert-ChildPath -Parent $runtimeRoot -Child $dataRoot
    Remove-Item -LiteralPath $dataRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $dataRoot, $mediaPath, $logRoot, $secretRoot -Force | Out-Null

$databaseUrlPath = $databasePath.Replace("\", "/")
$safeEnvironment = [ordered]@{
    APP_ENV = "development"
    ENV = "test"
    MODE = "test"
    IZO_RUNTIME_PROFILE = ""
    IZO_RELEASE_MANIFEST = ""
    FRONTEND_BUILD_LABEL = "local-test"
    APP_PUBLIC_URL = "http://127.0.0.1:$FrontendPort"
    BACKEND_PUBLIC_URL = "http://127.0.0.1:$BackendPort"
    DATABASE_URL = "sqlite:///$databaseUrlPath"
    MEDIA_DIR = $mediaPath
    IZO_SECRET_DIR = $secretRoot
    IZO_DISABLE_STARTUP_STORAGE_MAINTENANCE = "true"
    SESSION_HMAC_SECRET = "local-test-session-hmac-not-production"
    CORS_ALLOWED_ORIGINS = "http://127.0.0.1:$FrontendPort,http://localhost:$FrontendPort"
    TRUSTED_HOSTS = "127.0.0.1,localhost"
    TRUSTED_COOKIE_SECURE = "false"
    TRUSTED_COOKIE_SAMESITE = "lax"
    TRUSTED_COOKIE_PATH = "/"
    TRUST_PROXY_HEADERS = "false"
    TRUST_CLOUDFLARE_HEADERS = "false"
    BOT_UPDATES_MODE = "disabled"
    BOT_MODE = "disabled"
    MAX_UPDATES_MODE = "disabled"
    TELEGRAM_POLLING_ENABLED = "false"
    MAX_POLLING_ENABLED = "false"
    TELEGRAM_BOT_TOKEN = " "
    TELEGRAM_WEBHOOK_SECRET = " "
    TELEGRAM_BOT_USERNAME = " "
    TELEGRAM_BOT_DEEP_LINK_BASE = " "
    MAX_BOT_TOKEN = " "
    MAX_WEBHOOK_SECRET = " "
    MAX_WEBHOOK_URL = " "
    MAX_BOT_DEEP_LINK_BASE = " "
    MAX_API_BASE_URL = "http://127.0.0.1:9"
    MAX_TLS_TRUST_STORE = "system"
    OPENROUTER_API_KEY = " "
    SMTP_PASSWORD = " "
    SMTP_USERNAME = " "
    UNISENDER_API_KEY = " "
    YOOKASSA_SHOP_ID = " "
    YOOKASSA_SECRET_KEY = " "
    # Local testing must remain usable without a configured outbound mail service.
    # Password authentication stays enabled; email OTP is not advertised.
    EMAIL_PROVIDER = ""
    EMAIL_OTP_DEBUG_RETURN_CODE = "false"
    BILLING_SIMULATOR_ENABLED = "true"
    COMFYUI_REQUIRED = "false"
    COMFYUI_MOCK_FALLBACK = "true"
}
foreach ($entry in $safeEnvironment.GetEnumerator()) {
    Set-Item -Path "Env:$($entry.Key)" -Value ([string]$entry.Value)
}

$localEnvPath = Join-Path $backendRoot ".env"
if (Test-Path -LiteralPath $localEnvPath -PathType Leaf) {
    $localEnvKeys = @(
        Get-Content -LiteralPath $localEnvPath |
            ForEach-Object {
                if ($_ -match "^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=") {
                    $matches[1]
                }
            } |
            Sort-Object -Unique
    )
    $missingOverrides = @(
        $localEnvKeys | Where-Object { -not (Test-Path -LiteralPath "Env:$_") }
    )
    if ($missingOverrides.Count -gt 0) {
        throw "The isolated launcher does not override backend/.env key(s): $($missingOverrides -join ',')"
    }
}
if (Get-ChildItem -LiteralPath $secretRoot -Filter "*.dpapi.json" -File -ErrorAction SilentlyContinue) {
    throw "The isolated secret store is not empty. Remove only its test secret documents before starting."
}

$backendStdout = Join-Path $logRoot "backend.stdout.log"
$backendStderr = Join-Path $logRoot "backend.stderr.log"
$frontendStdout = Join-Path $logRoot "frontend.stdout.log"
$frontendStderr = Join-Path $logRoot "frontend.stderr.log"
foreach ($log in @($backendStdout, $backendStderr, $frontendStdout, $frontendStderr)) {
    if (Test-Path -LiteralPath $log) {
        Clear-Content -LiteralPath $log
    }
}

$backendProcess = $null
$frontendProcess = $null
try {
    $backendProcess = Start-Process `
        -FilePath $python `
        -ArgumentList @(
            "-m", "uvicorn", "main:app",
            "--app-dir", "`"$backendRoot`"",
            "--host", "127.0.0.1",
            "--port", [string]$BackendPort,
            "--no-proxy-headers"
        ) `
        -WorkingDirectory $backendRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $backendStdout `
        -RedirectStandardError $backendStderr `
        -PassThru

    $health = Wait-HttpJson -Uri "http://127.0.0.1:$BackendPort/api/health"
    if (-not $health.ready) {
        throw "The isolated backend health endpoint is not ready."
    }
    $capabilities = Wait-HttpJson -Uri "http://127.0.0.1:$BackendPort/api/auth/capabilities-v2"
    if (
        $capabilities.bot_login.telegram_bot_login_available -or
        $capabilities.bot_login.max_bot_login_available
    ) {
        throw "Real bot login capability leaked into the isolated test backend."
    }
    if ($capabilities.email_otp_available) {
        throw "Email OTP capability leaked into the isolated test backend."
    }

    $frontendProcess = Start-Process `
        -FilePath $node `
        -ArgumentList @(
            "`"$viteScript`"",
            "--host", "127.0.0.1",
            "--port", [string]$FrontendPort,
            "--strictPort"
        ) `
        -WorkingDirectory $frontendRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $frontendStdout `
        -RedirectStandardError $frontendStderr `
        -PassThru

    $frontend = Wait-HttpStatus -Uri "http://127.0.0.1:$FrontendPort/"
    $proxiedHealth = Wait-HttpJson -Uri "http://127.0.0.1:$FrontendPort/api/health"
    if (-not $proxiedHealth.ready) {
        throw "The frontend proxy did not return a ready isolated backend."
    }

    $backendListenerPid = Get-ListenerPid -Port $BackendPort
    $frontendListenerPid = Get-ListenerPid -Port $FrontendPort
    $git = Get-Command git.exe -ErrorAction SilentlyContinue
    $gitSha = if ($git) {
        (& $git.Source -C $root rev-parse HEAD 2>$null | Select-Object -First 1).Trim()
    } else {
        "unknown"
    }

    $manifest = [ordered]@{
        version = 1
        started_at = [DateTime]::UtcNow.ToString("o")
        git_sha = $gitSha
        repo_root = $root
        database_path = $databasePath
        media_path = $mediaPath
        secret_path = $secretRoot
        backend = [ordered]@{
            port = $BackendPort
            launch_pid = $backendProcess.Id
            listener_pid = $backendListenerPid
            expected_command_path = $backendRoot
        }
        frontend = [ordered]@{
            port = $FrontendPort
            launch_pid = $frontendProcess.Id
            listener_pid = $frontendListenerPid
            expected_command_path = $viteScript
        }
    }
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

    Write-Host "LOCAL_TEST_BACKEND_OK pid=$backendListenerPid ready=true"
    Write-Host "LOCAL_TEST_FRONTEND_OK pid=$frontendListenerPid status=$($frontend.StatusCode)"
    Write-Host "LOCAL_TEST_STACK_OK url=http://127.0.0.1:$FrontendPort manifest=$manifestPath"

    if ($OpenBrowser) {
        Start-Process "http://127.0.0.1:$FrontendPort/"
    }
} catch {
    Stop-StartedProcess -Process $frontendProcess
    Stop-StartedProcess -Process $backendProcess
    Write-Error $_
    exit 1
}
