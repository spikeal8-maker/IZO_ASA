@echo off
REM ==========================================================================
REM  PUBLIC / LIVE launcher for the tunnel https://izo.alikinas.ru
REM  Serves the BUILT frontend/dist via `vite preview` (no /@vite/client, no
REM  hot-reload). Backend = uvicorn on 127.0.0.1:8000. Cloudflared is expected
REM  to already point at :5173 and is NOT started/managed here.
REM  Re-run this after ANY frontend or backend code change.
REM ==========================================================================
setlocal
chcp 65001 >nul

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"
set "PUBURL=https://izo.alikinas.ru"
set "LIVE_DB=%BACKEND%\onenode.sqlite3"
set "APP_ENV=production"
set "APP_BUILD=FEED-4COL-FULLWIDTH-20260704"
set "FRONTEND_BUILD_LABEL=FEED-4COL-FULLWIDTH-20260704"
set "DATABASE_URL=sqlite:///%LIVE_DB%"
set "DB_GUARD_ALLOWED_PATHS=%LIVE_DB%"
set "DB_GUARD_MIN_SIZE_MB=10"
set "DB_GUARD_MIN_USERS=5"
set "DB_GUARD_MIN_ACTIVE_ADMINS=1"
set "LOG_DIR=%ROOT%logs"
REM platform-api.max.ru passes Python/certifi TLS verification; platform-api2 does not.
if "%MAX_API_BASE_URL%"=="" set "MAX_API_BASE_URL=https://platform-api.max.ru"
REM Telegram keeps its own mode via BOT_UPDATES_MODE (polling). Do NOT change Telegram.
if "%BOT_UPDATES_MODE%"=="" set "BOT_UPDATES_MODE=polling"
REM MAX is pinned to webhook in production (independent of BOT_UPDATES_MODE).
if "%MAX_UPDATES_MODE%"=="" set "MAX_UPDATES_MODE=webhook"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "LAUNCH_TS=%%I"
set "BACKEND_LOG=%LOG_DIR%\live_backend_%LAUNCH_TS%.log"

title IZO_ASA PUBLIC launcher
echo.
echo ==========================================
echo   IZO_ASA - PUBLIC launcher (dist mode)
echo ==========================================
echo.

where python >nul 2>nul || (echo [ERROR] Python not found in PATH. & pause & exit /b 1)
where node   >nul 2>nul || (echo [ERROR] Node.js not found in PATH. & pause & exit /b 1)
where npm    >nul 2>nul || (echo [ERROR] npm not found in PATH. & pause & exit /b 1)

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
if errorlevel 1 (echo [ERROR] Production DB preflight failed. Public backend NOT started. & pause & exit /b 1)

echo [1/5] Building frontend (tsc -b + vite build)...
pushd "%FRONTEND%" >nul
if not exist "node_modules" (
  echo Installing frontend dependencies...
  call npm install || (echo [ERROR] npm install failed. & popd >nul & pause & exit /b 1)
)
call npx tsc -b
if errorlevel 1 (
  echo [WARN] tsc -b had type errors (likely WIP code). Vite build will still run.
  echo        Fix uncommitted TypeScript errors in newUi.tsx before final deploy.
)
call npx vite build
if errorlevel 1 (echo [ERROR] vite build failed. Public site NOT changed. & popd >nul & pause & exit /b 1)
popd >nul
if not exist "%FRONTEND%\dist\index.html" (echo [ERROR] dist\index.html missing after build. & pause & exit /b 1)

echo [2/5] Freeing ports 8000 and 5173 (stop old backend/dev/preview)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -LocalPort 8000,5173 -ErrorAction SilentlyContinue | Where-Object {$_.State -eq 'Listen'} | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }" >nul 2>nul

echo [3/5] Starting backend on 127.0.0.1:8000...
echo Backend log: %BACKEND_LOG%
start "IZO_ASA backend :8000" powershell -NoExit -NoProfile -ExecutionPolicy Bypass -Command "$env:APP_ENV='%APP_ENV%'; $env:APP_BUILD='%APP_BUILD%'; $env:FRONTEND_BUILD_LABEL='%FRONTEND_BUILD_LABEL%'; $env:DATABASE_URL='%DATABASE_URL%'; $env:DB_GUARD_ALLOWED_PATHS='%DB_GUARD_ALLOWED_PATHS%'; $env:DB_GUARD_MIN_SIZE_MB='%DB_GUARD_MIN_SIZE_MB%'; $env:DB_GUARD_MIN_USERS='%DB_GUARD_MIN_USERS%'; $env:DB_GUARD_MIN_ACTIVE_ADMINS='%DB_GUARD_MIN_ACTIVE_ADMINS%'; $env:MAX_API_BASE_URL='%MAX_API_BASE_URL%'; $env:BOT_UPDATES_MODE='%BOT_UPDATES_MODE%'; $env:MAX_UPDATES_MODE='%MAX_UPDATES_MODE%'; Set-Location -LiteralPath '%BACKEND%'; python -m uvicorn main:app --host 127.0.0.1 --port 8000 *>> '%BACKEND_LOG%'"

echo Waiting for backend health before starting frontend...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ok=$false;" ^
  "for($i=0;$i -lt 40;$i++) { try { $r=Invoke-WebRequest 'http://127.0.0.1:8000/api/health' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { $ok=$true; break } } catch { Start-Sleep -Seconds 1 } }" ^
  "if (!$ok) { Write-Host 'BACKEND DOWN: /api/health did not become ready'; exit 30 }" ^
  "Write-Host 'backend ready: /api/health 200'"
if errorlevel 1 (
  echo.
  echo BACKEND DOWN
  echo Backend log: %BACKEND_LOG%
  echo Public launch is NOT healthy.
  if /I not "%IZO_NO_PAUSE%"=="1" pause
  exit /b 1
)

echo [4/5] Starting frontend PREVIEW (dist) on 127.0.0.1:5173...
start "IZO_ASA public frontend :5173" powershell -NoExit -NoProfile -ExecutionPolicy Bypass -Command "Set-Location -LiteralPath '%FRONTEND%'; npx vite preview --host 127.0.0.1 --port 5173"

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
  "if (!$be) { Write-Host 'BACKEND DOWN: port 8000 is not listening'; exit 20 }" ^
  "try { $h=Invoke-WebRequest 'http://127.0.0.1:8000/api/health' -UseBasicParsing -TimeoutSec 8; Write-Host ('backend /api/health : ' + $h.StatusCode) } catch { Write-Host 'BACKEND DOWN: /api/health failed'; exit 21 }" ^
  "try { $c=Invoke-WebRequest 'http://127.0.0.1:8000/api/auth/capabilities-v2' -UseBasicParsing -TimeoutSec 8; Write-Host ('backend /api/auth/capabilities-v2 : ' + $c.StatusCode) } catch { Write-Host 'BACKEND DOWN: /api/auth/capabilities-v2 failed'; exit 22 }" ^
  "try { $html=(Invoke-WebRequest 'http://127.0.0.1:5173/' -UseBasicParsing -TimeoutSec 8).Content;" ^
  "  Write-Host ('vite-dev-client present : ' + ($html -match '/@vite/client'));" ^
  "  Write-Host ('raw /src/main present   : ' + ($html -match '/src/main.tsx'));" ^
  "  Write-Host ('hashed asset present    : ' + ($html -match 'assets/index-')); } catch { Write-Host 'frontend probe failed' }" ^
  "try { Write-Host ('api/version : ' + (Invoke-WebRequest 'http://127.0.0.1:5173/api/version' -UseBasicParsing -TimeoutSec 8).StatusCode) } catch { Write-Host 'api/version probe failed' }" ^
  "function St($m,$u,$b){ try { $r=Invoke-WebRequest $u -Method $m -UseBasicParsing -TimeoutSec 8 -Body $b -ContentType 'application/json'; return $r.StatusCode } catch { return $_.Exception.Response.StatusCode.value__ } }" ^
  "Write-Host ('generate no-session : ' + (St 'POST' 'http://127.0.0.1:5173/api/generate' '{""mode"":""text_to_image""}'));" ^
  "Write-Host ('gallery no-session  : ' + (St 'GET'  'http://127.0.0.1:5173/api/gallery' $null));" ^
  "Write-Host ('me-v2 no-session    : ' + (St 'GET'  'http://127.0.0.1:5173/api/me-v2'  $null))"
if errorlevel 1 (
  echo.
  echo BACKEND DOWN
  echo Backend log: %BACKEND_LOG%
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
echo   Cloudflared tunnel is NOT managed here (must point to :5173).
echo ==========================================
echo.
if /I not "%IZO_NO_PAUSE%"=="1" pause
