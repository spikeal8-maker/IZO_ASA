@echo off
REM ==========================================================================
REM  Stops the PUBLIC backend (uvicorn :8000) and local Caddy edge (:5173).
REM  FRP is intentionally left running. No destructive operations are performed;
REM  this script stops only the two local listening processes.
REM ==========================================================================
setlocal
chcp 65001 >nul
title IZO_ASA stop-public

echo Stopping local Caddy edge (:5173) with ownership validation...
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0tools\stop-caddy.ps1" -RepoRoot "%~dp0"
if errorlevel 1 (
  echo [ERROR] Caddy stop was refused or failed. Backend was left running.
  pause
  exit /b 1
)

echo Stopping backend (:8000)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Where-Object {$_.State -eq 'Listen'} | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { try { Stop-Process -Id $_ -Force -ErrorAction Stop; Write-Host ('stopped backend PID ' + $_) } catch {} }"

echo Done. (FRP left running.)
echo.
pause
