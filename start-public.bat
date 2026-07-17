@echo off
REM ==========================================================================
REM  PUBLIC / LIVE launcher for the tunnel https://izo.alikinas.ru
REM  Serves the BUILT frontend/dist via `vite preview` (no /@vite/client, no
REM  hot-reload). Backend = uvicorn on 127.0.0.1:8000. The autostart wrapper
REM  starts and verifies the FRP tunnel after this launcher becomes healthy.
REM  Re-run this after ANY frontend or backend code change.
REM ==========================================================================
setlocal
chcp 65001 >nul

REM Auto-skip pause when launched non-interactively (e.g. Task Scheduler).
REM Set IZO_NO_PAUSE=1 manually to skip pauses in interactive runs too.
echo|pause >nul 2>nul && (set "HAS_CONSOLE=1") || (set "IZO_NO_PAUSE=1")

set "ROOT=%~dp0"
set "ROOT_NO_SLASH=%ROOT:~0,-1%"
set "BACKEND=%ROOT%backend"
set "PUBURL=https://izo.alikinas.ru"
set "LIVE_DB=%BACKEND%\onenode.sqlite3"
set "PYTHON_EXE=%BACKEND%\.venv\Scripts\python.exe"
set "APP_ENV=production"
set "DATABASE_URL=sqlite:///%LIVE_DB%"
set "DB_GUARD_ALLOWED_PATHS=%LIVE_DB%"
set "DB_GUARD_MIN_SIZE_MB=10"
set "DB_GUARD_MIN_USERS=5"
set "DB_GUARD_MIN_ACTIVE_ADMINS=1"
set "TRUSTED_COOKIE_SECURE=true"
set "TRUSTED_COOKIE_SAMESITE=none"
set "TRUSTED_COOKIE_PATH=/"
set "TRUST_CLOUDFLARE_HEADERS=true"
REM MAX API2 uses the native system trust store through backend truststore support.
if "%MAX_API_BASE_URL%"=="" set "MAX_API_BASE_URL=https://platform-api2.max.ru"
REM Telegram keeps its own mode via BOT_UPDATES_MODE (polling). Do NOT change Telegram.
if "%BOT_UPDATES_MODE%"=="" set "BOT_UPDATES_MODE=polling"
REM Keep the currently proven MAX polling path unless webhook mode is set explicitly
REM together with MAX_WEBHOOK_SECRET. Do not switch delivery modes implicitly.
if "%MAX_UPDATES_MODE%"=="" set "MAX_UPDATES_MODE=polling"

title IZO_ASA PUBLIC launcher
echo.
echo ==========================================
echo   IZO_ASA - PUBLIC launcher (dist mode)
echo ==========================================
echo.

REM A configured STANDBY must never start a writing backend automatically.
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%ROOT%ops\backup\check_server_role.ps1"
if errorlevel 1 (
  echo [ERROR] Server role guard refused public startup.
  if /I not "%IZO_NO_PAUSE%"=="1" pause
  exit /b 1
)

if not exist "%PYTHON_EXE%" (
  echo [ERROR] Project Python not found: backend\.venv\Scripts\python.exe
  if /I not "%IZO_NO_PAUSE%"=="1" pause
  exit /b 1
)
where node >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Node.js not found in PATH.
  if /I not "%IZO_NO_PAUSE%"=="1" pause
  exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] npm not found in PATH.
  if /I not "%IZO_NO_PAUSE%"=="1" pause
  exit /b 1
)

echo [0/5] Production DB safety preflight...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$db='%LIVE_DB%';" ^
  "$root='%ROOT%';" ^
  "if ($root -match '(?i)(_izo_asa_.*clean|clean_worktree|temp|tmp)') { Write-Host '[ERROR] Refusing public launch from temporary/clean worktree:' $root; exit 10 }" ^
  "if (!(Test-Path -LiteralPath $db)) { Write-Host '[ERROR] Live DB not found:' $db; exit 11 }" ^
  "$item=Get-Item -LiteralPath $db;" ^
  "$size=[math]::Round($item.Length/1MB,2);" ^
  "Write-Host ('Live DB confirmed: .../' + (Split-Path (Split-Path $db -Parent) -Leaf) + '/' + (Split-Path $db -Leaf) + ' (' + $size + ' MB)');" ^
  "if ($item.Length -lt 10MB) { Write-Host '[ERROR] Refusing suspiciously small live DB:' $size 'MB'; exit 12 }"
if errorlevel 1 (
  echo [ERROR] Production DB preflight failed. Public backend NOT started.
  if /I not "%IZO_NO_PAUSE%"=="1" pause
  exit /b 1
)

echo [1/5] Verifying exact checkout, writing receipt, and preparing immutable frontend release...
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%ROOT%tools\publish-frontend-release.ps1" -RepoRoot "%ROOT_NO_SLASH%" -PythonPath "%PYTHON_EXE%"
if errorlevel 1 (
  echo [ERROR] Candidate release failed. The active public release was NOT changed.
  if /I not "%IZO_NO_PAUSE%"=="1" pause
  exit /b 1
)
for /f "delims=" %%I in ('powershell -NoProfile -Command "(ConvertFrom-Json (Get-Content -LiteralPath '%ROOT%.runtime\active-frontend.json' -Raw)).release_path"') do set "FRONTEND_RELEASE=%%I"
for /f "delims=" %%I in ('powershell -NoProfile -Command "(ConvertFrom-Json (Get-Content -LiteralPath '%ROOT%.runtime\active-frontend.json' -Raw)).release_manifest"') do set "RELEASE_MANIFEST=%%I"
for /f "delims=" %%I in ('powershell -NoProfile -Command "(ConvertFrom-Json (Get-Content -LiteralPath '%ROOT%.runtime\active-frontend.json' -Raw)).active_release"') do set "APP_BUILD=%%I"
for /f "delims=" %%I in ('powershell -NoProfile -Command "(ConvertFrom-Json (Get-Content -LiteralPath '%ROOT%.runtime\active-frontend.json' -Raw)).previous_release"') do set "PREVIOUS_RELEASE=%%I"
set "FRONTEND_BUILD_LABEL=%APP_BUILD%"
if not exist "%FRONTEND_RELEASE%\index.html" (
  echo [ERROR] Active release index.html missing.
  if /I not "%IZO_NO_PAUSE%"=="1" pause
  exit /b 1
)
if not exist "%RELEASE_MANIFEST%" (
  echo [ERROR] Immutable release manifest missing.
  if /I not "%IZO_NO_PAUSE%"=="1" pause
  exit /b 1
)

echo [2/5] Controlled backend restart from immutable release manifest...
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%ROOT%tools\restart-backend.ps1" -RepoRoot "%ROOT_NO_SLASH%" -PythonPath "%PYTHON_EXE%" -ReleaseManifestPath "%RELEASE_MANIFEST%" -AllowColdStart
if errorlevel 1 (
  echo.
  echo [ERROR] Production backend release failed; restart script attempted backend rollback.
  if not "%PREVIOUS_RELEASE%"=="" powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%ROOT%tools\rollback-frontend-release.ps1" -RepoRoot "%ROOT_NO_SLASH%" -ReleaseId "%PREVIOUS_RELEASE%"
  if /I not "%IZO_NO_PAUSE%"=="1" pause
  exit /b 1
)

echo [3/5] Backend release identity verified by restart-backend.ps1.
echo [4/5] Immutable frontend release is already active on 127.0.0.1:5173.

echo [5/5] Waiting for frontend, then probing...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ok=$false;" ^
  "for($i=0;$i -lt 30;$i++) { try { $r=Invoke-WebRequest 'http://127.0.0.1:5173/' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { $ok=$true; break } } catch { Start-Sleep -Seconds 1 } }" ^
  "if (!$ok) { Write-Host 'FRONTEND DOWN: / did not become ready'; exit 31 }" ^
  "Write-Host 'frontend ready: / 200'"
if errorlevel 1 (
  echo.
  echo FRONTEND DOWN
  echo Public launch is NOT healthy.
  if /I not "%IZO_NO_PAUSE%"=="1" pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$be=(Get-NetTCPConnection -LocalPort 8000 -State Listen -EA SilentlyContinue).OwningProcess | Select-Object -Unique;" ^
  "$fe=(Get-NetTCPConnection -LocalPort 5173 -State Listen -EA SilentlyContinue).OwningProcess | Select-Object -Unique;" ^
  "Write-Host ('backend PID  : ' + $be);" ^
  "Write-Host ('frontend PID : ' + $fe);" ^
  "Write-Host ('MAX_BOT_TOKEN set          : ' + [bool]$env:MAX_BOT_TOKEN);" ^
  "Write-Host ('MAX_BOT_DEEP_LINK_BASE set : ' + [bool]$env:MAX_BOT_DEEP_LINK_BASE);" ^
  "Write-Host ('MAX_API_BASE_URL           : ' + $env:MAX_API_BASE_URL);" ^
  "Write-Host ('BOT_UPDATES_MODE           : ' + $env:BOT_UPDATES_MODE);" ^
  "Write-Host ('MAX_UPDATES_MODE           : ' + $env:MAX_UPDATES_MODE);" ^
  "Write-Host ('TRUSTED_COOKIE_SAMESITE    : ' + $env:TRUSTED_COOKIE_SAMESITE);" ^
  "if (!$be) { Write-Host 'BACKEND DOWN: port 8000 is not listening'; exit 20 }" ^
  "try { $h=Invoke-WebRequest 'http://127.0.0.1:8000/api/health' -UseBasicParsing -TimeoutSec 8; Write-Host ('backend /api/health : ' + $h.StatusCode) } catch { Write-Host 'BACKEND DOWN: /api/health failed'; exit 21 }" ^
  "try { $c=Invoke-WebRequest 'http://127.0.0.1:8000/api/auth/capabilities-v2' -UseBasicParsing -TimeoutSec 8; Write-Host ('backend /api/auth/capabilities-v2 : ' + $c.StatusCode) } catch { Write-Host 'BACKEND DOWN: /api/auth/capabilities-v2 failed'; exit 22 }" ^
  "try { $html=(Invoke-WebRequest 'http://127.0.0.1:5173/' -UseBasicParsing -TimeoutSec 8).Content;" ^
  "  $releaseMarker='name=' + [char]34 + 'izo-release' + [char]34 + ' content=' + [char]34 + '%APP_BUILD%' + [char]34;" ^
  "  $releaseMetaMatches=$html.Contains($releaseMarker);" ^
  "  Write-Host ('vite-dev-client present : ' + ($html -match '/@vite/client'));" ^
  "  Write-Host ('raw /src/main present   : ' + ($html -match '/src/main.tsx'));" ^
  "  Write-Host ('hashed asset present    : ' + ($html -match 'assets/index-'));" ^
  "  Write-Host ('release meta matches    : ' + $releaseMetaMatches);" ^
  "  if (!$releaseMetaMatches) { Write-Host 'FRONTEND RELEASE MISMATCH'; exit 25 } } catch { Write-Host 'frontend probe failed'; exit 25 }" ^
  "foreach($route in @('/feed','/gallery')) { try { $shell=Invoke-WebRequest ('http://127.0.0.1:5173' + $route) -UseBasicParsing -TimeoutSec 8; $shellRelease=[string]$shell.Headers['X-IZO-Release']; Write-Host ('shell release ' + $route + ' : ' + $shellRelease); if ($shellRelease -ne '%APP_BUILD%') { Write-Host 'STATIC SHELL RELEASE MISMATCH'; exit 26 } } catch { Write-Host ('static shell probe failed: ' + $route); exit 26 } };" ^
  "try { $v=Invoke-RestMethod 'http://127.0.0.1:5173/api/version' -TimeoutSec 8; Write-Host ('api/version release : ' + $v.release_id); if ($v.release_id -ne '%APP_BUILD%' -or $v.frontend_build -ne '%APP_BUILD%') { Write-Host 'RELEASE IDENTITY MISMATCH'; exit 24 } } catch { Write-Host 'api/version probe failed'; exit 24 }" ^
  "function St($m,$u,$b){ try { $r=Invoke-WebRequest $u -Method $m -UseBasicParsing -TimeoutSec 8 -Body $b -ContentType 'application/json'; return $r.StatusCode } catch { return $_.Exception.Response.StatusCode.value__ } };" ^
  "$generateBody=@{mode='text_to_image'} | ConvertTo-Json -Compress;" ^
  "$generateStatus=St 'POST' 'http://127.0.0.1:5173/api/generate' $generateBody;" ^
  "$galleryStatus=St 'GET' 'http://127.0.0.1:5173/api/gallery' $null;" ^
  "$meStatus=St 'GET' 'http://127.0.0.1:5173/api/me-v2' $null;" ^
  "Write-Host ('generate no-session : ' + $generateStatus);" ^
  "Write-Host ('gallery no-session  : ' + $galleryStatus);" ^
  "Write-Host ('me-v2 no-session    : ' + $meStatus);" ^
  "if ($generateStatus -ne 401 -or $galleryStatus -ne 401 -or $meStatus -ne 401) { Write-Host 'AUTH SMOKE FAILED: expected 401 from generate/gallery/me-v2'; exit 23 }"
if errorlevel 1 (
  echo.
  echo BACKEND DOWN
  echo Public launch is NOT healthy.
  if /I not "%IZO_NO_PAUSE%"=="1" pause
  exit /b 1
)

echo.
echo ==========================================
echo   PUBLIC mode started (dist via vite preview).
echo   Public URL: %PUBURL%
echo   Expect: vite-dev-client=False, hashed asset=True, api/version=200,
echo           generate/gallery/me no-session=401.
echo   NOTE: frontend code changes require re-running start-public.bat.
echo   FRP tunnel is managed and verified by start-public-autostart.bat.
echo ==========================================
echo.
if /I not "%IZO_NO_PAUSE%"=="1" pause
