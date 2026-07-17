@echo off
REM ==========================================================================
REM  Stops the PUBLIC backend (uvicorn :8000) and frontend preview (:5173).
REM  FRP is intentionally left running. No destructive operations are performed;
REM  this script stops only the two local listening processes.
REM ==========================================================================
setlocal
chcp 65001 >nul
title IZO_ASA stop-public

echo Stopping backend (:8000) and frontend preview (:5173)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -LocalPort 8000,5173 -ErrorAction SilentlyContinue | Where-Object {$_.State -eq 'Listen'} | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { try { Stop-Process -Id $_ -Force -ErrorAction Stop; Write-Host ('stopped PID ' + $_) } catch {} }"

echo Done. (FRP left running.)
echo.
pause
