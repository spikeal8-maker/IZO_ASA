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

echo [%DATE% %TIME%] start-public.bat exited with %EXIT_CODE% >> "%LOG_FILE%"
exit /b %EXIT_CODE%
