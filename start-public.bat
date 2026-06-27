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

title IZO_ASA PUBLIC launcher
echo.
echo ==========================================
echo   IZO_ASA - PUBLIC launcher (dist mode)
echo ==========================================
echo.

where python >nul 2>nul || (echo [ERROR] Python not found in PATH. & pause & exit /b 1)
where node   >nul 2>nul || (echo [ERROR] Node.js not found in PATH. & pause & exit /b 1)
where npm    >nul 2>nul || (echo [ERROR] npm not found in PATH. & pause & exit /b 1)

echo [1/5] Building frontend (tsc -b + vite build)...
pushd "%FRONTEND%" >nul
if not exist "node_modules" (
  echo Installing frontend dependencies...
  call npm install || (echo [ERROR] npm install failed. & popd >nul & pause & exit /b 1)
)
call npx tsc -b
if errorlevel 1 (echo [ERROR] tsc -b failed. Public site NOT changed. & popd >nul & pause & exit /b 1)
call npx vite build
if errorlevel 1 (echo [ERROR] vite build failed. Public site NOT changed. & popd >nul & pause & exit /b 1)
popd >nul
if not exist "%FRONTEND%\dist\index.html" (echo [ERROR] dist\index.html missing after build. & pause & exit /b 1)

echo [2/5] Freeing ports 8000 and 5173 (stop old backend/dev/preview)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -LocalPort 8000,5173 -ErrorAction SilentlyContinue | Where-Object {$_.State -eq 'Listen'} | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }" >nul 2>nul

echo [3/5] Starting backend on 127.0.0.1:8000...
start "IZO_ASA backend :8000" powershell -NoExit -NoProfile -ExecutionPolicy Bypass -Command "Set-Location -LiteralPath '%BACKEND%'; python -m uvicorn main:app --host 127.0.0.1 --port 8000"

echo [4/5] Starting frontend PREVIEW (dist) on 127.0.0.1:5173...
start "IZO_ASA public frontend :5173" powershell -NoExit -NoProfile -ExecutionPolicy Bypass -Command "Set-Location -LiteralPath '%FRONTEND%'; npx vite preview --host 127.0.0.1 --port 5173"

echo [5/5] Waiting for services, then probing...
timeout /t 6 /nobreak >nul

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$be=(Get-NetTCPConnection -LocalPort 8000 -State Listen -EA SilentlyContinue).OwningProcess | Select-Object -Unique;" ^
  "$fe=(Get-NetTCPConnection -LocalPort 5173 -State Listen -EA SilentlyContinue).OwningProcess | Select-Object -Unique;" ^
  "Write-Host ('backend PID  : ' + $be);" ^
  "Write-Host ('frontend PID : ' + $fe);" ^
  "try { $html=(Invoke-WebRequest 'http://127.0.0.1:5173/' -UseBasicParsing -TimeoutSec 8).Content;" ^
  "  Write-Host ('vite-dev-client present : ' + ($html -match '/@vite/client'));" ^
  "  Write-Host ('raw /src/main present   : ' + ($html -match '/src/main.tsx'));" ^
  "  Write-Host ('hashed asset present    : ' + ($html -match 'assets/index-')); } catch { Write-Host 'frontend probe failed' }" ^
  "try { Write-Host ('api/version : ' + (Invoke-WebRequest 'http://127.0.0.1:5173/api/version' -UseBasicParsing -TimeoutSec 8).StatusCode) } catch { Write-Host 'api/version probe failed' }" ^
  "function St($m,$u,$b){ try { $r=Invoke-WebRequest $u -Method $m -UseBasicParsing -TimeoutSec 8 -Body $b -ContentType 'application/json'; return $r.StatusCode } catch { return $_.Exception.Response.StatusCode.value__ } }" ^
  "Write-Host ('generate no-session : ' + (St 'POST' 'http://127.0.0.1:5173/api/generate' '{""mode"":""text_to_image""}'));" ^
  "Write-Host ('gallery no-session  : ' + (St 'GET'  'http://127.0.0.1:5173/api/gallery' $null));" ^
  "Write-Host ('me-v2 no-session    : ' + (St 'GET'  'http://127.0.0.1:5173/api/me-v2'  $null))"

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
pause
