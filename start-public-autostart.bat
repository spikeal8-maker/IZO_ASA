@echo off
setlocal
chcp 65001 >nul

set "ROOT=%~dp0"
set "LOG_DIR=%ROOT%logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

set "LAUNCH_TS=%DATE%_%TIME%"
set "LAUNCH_TS=%LAUNCH_TS:/=-%"
set "LAUNCH_TS=%LAUNCH_TS:.=-%"
set "LAUNCH_TS=%LAUNCH_TS::=-%"
set "LAUNCH_TS=%LAUNCH_TS: =_%"
set "LOG_FILE=%LOG_DIR%\autostart_%LAUNCH_TS%.log"
set "LATEST_LOG=%LOG_DIR%\autostart_latest.log"

echo [%DATE% %TIME%] IZO ASA autostart wrapper > "%LOG_FILE%"
echo ROOT=%ROOT% >> "%LOG_FILE%"
echo USER=%USERNAME% >> "%LOG_FILE%"
echo COMPUTER=%COMPUTERNAME% >> "%LOG_FILE%"
echo Latest log: %LOG_FILE% > "%LATEST_LOG%"

cd /d "%ROOT%"
set "IZO_NO_PAUSE=1"

call "%ROOT%start-public.bat" >> "%LOG_FILE%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"

if "%EXIT_CODE%"=="0" (
  echo [%DATE% %TIME%] Ensuring FRP public tunnel... >> "%LOG_FILE%"
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$exe='C:\frp\frpc.exe'; $config='C:\frp\frpc.toml';" ^
    "if (!(Test-Path -LiteralPath $exe) -or !(Test-Path -LiteralPath $config)) { Write-Host '[ERROR] FRP executable or config is missing'; exit 40 };" ^
    "if (!(Get-Process frpc -ErrorAction SilentlyContinue)) { Start-Process -FilePath $exe -ArgumentList @('-c',$config) -WorkingDirectory 'C:\frp' -WindowStyle Hidden };" ^
    "$ok=$false; for($i=0;$i -lt 30;$i++) { try { $r=Invoke-WebRequest 'https://izo.alikinas.ru/api/health' -UseBasicParsing -TimeoutSec 4; if ($r.StatusCode -eq 200) { $ok=$true; break } } catch {}; Start-Sleep -Seconds 2 };" ^
    "if (!$ok) { Write-Host '[ERROR] FRP started but public health check failed'; exit 41 }; Write-Host 'FRP ready: public /api/health 200'" >> "%LOG_FILE%" 2>&1
  if errorlevel 1 set "EXIT_CODE=%ERRORLEVEL%"
)

echo [%DATE% %TIME%] start-public.bat exited with %EXIT_CODE% >> "%LOG_FILE%"
exit /b %EXIT_CODE%
