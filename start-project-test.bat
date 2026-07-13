@echo off
REM ==========================================================================
REM  DEV ONLY. Do not use this file for the public tunnel izo.alikinas.ru.
REM  This starts the Vite DEV server on :5173 (hot-reload, raw /src source),
REM  which causes blinking/state-reset on the public URL and stale mobile cache.
REM  For the public tunnel use start-public.bat (serves built frontend/dist).
REM ==========================================================================
setlocal
chcp 65001 >nul

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"
set "URL=http://127.0.0.1:5173"

title IZO_ASA launcher
echo.
echo ==========================================
echo   IZO_ASA - local launcher  [ DEV ONLY ]
echo ==========================================
echo.
echo   WARNING: DEV mode (Vite dev server on :5173).
echo   Do NOT use for the public tunnel izo.alikinas.ru.
echo   For public/live use start-public.bat instead.
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found in PATH.
  echo Install Python 3.11+ or add it to PATH.
  pause
  exit /b 1
)

where node >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Node.js not found in PATH.
  echo Install Node.js LTS and run this file again.
  pause
  exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] npm not found in PATH.
  echo Reinstall Node.js LTS and run this file again.
  pause
  exit /b 1
)

echo [1/5] Checking backend dependencies...
pushd "%BACKEND%" >nul
python -c "import fastapi, uvicorn, httpx, PIL" >nul 2>nul
if errorlevel 1 (
  echo Installing backend dependencies...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [ERROR] Backend dependency install failed.
    popd >nul
    pause
    exit /b 1
  )
)
popd >nul

echo [2/5] Checking frontend dependencies...
if not exist "%FRONTEND%\node_modules" (
  pushd "%FRONTEND%" >nul
  echo Installing frontend dependencies...
  call npm install
  if errorlevel 1 (
    echo [ERROR] Frontend dependency install failed.
    popd >nul
    pause
    exit /b 1
  )
  popd >nul
)

echo [3/5] Freeing ports 8000 and 5173...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -LocalPort 8000,5173 -ErrorAction SilentlyContinue | Where-Object {$_.State -eq 'Listen'} | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }" >nul 2>nul

echo [4/5] Starting backend...
start "IZO_ASA backend :8000" powershell -NoExit -NoProfile -ExecutionPolicy Bypass -Command "Set-Location -LiteralPath '%BACKEND%'; python -m uvicorn main:app --host 127.0.0.1 --port 8000 --no-proxy-headers"

echo [5/5] Starting frontend...
start "IZO_ASA frontend :5173" powershell -NoExit -NoProfile -ExecutionPolicy Bypass -Command "Set-Location -LiteralPath '%FRONTEND%'; npm.cmd run dev -- --host 127.0.0.1 --port 5173"

echo.
echo Waiting a few seconds, then opening:
echo %URL%
timeout /t 5 /nobreak >nul
start "" "%URL%"

echo.
echo Done. Keep the backend/frontend windows open while working.
echo Close those windows to stop the project.
echo.
pause
