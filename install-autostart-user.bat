@echo off
setlocal
chcp 65001 >nul

set "ROOT=%~dp0"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "TARGET=%STARTUP%\IZO_ASA_Public_Autostart.bat"

if not exist "%STARTUP%" mkdir "%STARTUP%"

(
  echo @echo off
  echo chcp 65001 ^>nul
  echo cd /d "%ROOT%"
  echo call "%ROOT%start-public-autostart.bat"
) > "%TARGET%"

echo Installed user autostart:
echo %TARGET%
echo.
echo It will run after Windows user login and write logs to:
echo %ROOT%logs\autostart_latest.log
