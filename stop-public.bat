@echo off
REM ==========================================================================
REM  Stops the PUBLIC backend (uvicorn :8000) and frontend preview (:5173).
REM  Cloudflared is intentionally left running (it is not started by the public
REM  launcher). No destructive operations — only stops the two listening procs.
REM ==========================================================================
setlocal
chcp 65001 >nul
title IZO_ASA stop-public

echo Stopping backend (:8000) and frontend preview (:5173)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -LocalPort 8000,5173 -ErrorAction SilentlyContinue | Where-Object {$_.State -eq 'Listen'} | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { try { Stop-Process -Id $_ -Force -ErrorAction Stop; Write-Host ('stopped PID ' + $_) } catch {} }"

echo Done. (Cloudflared left running.)
echo.
pause
