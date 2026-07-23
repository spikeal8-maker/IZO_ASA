@echo off
setlocal
chcp 65001 >nul

set "ROOT=%~dp0"

echo.
echo ==========================================
echo   IZO_ASA - isolated local test stack
echo ==========================================
echo.
echo   Database/media: .runtime\local-test
echo   Providers: fake/disabled
echo   Public tunnel: not started
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%tools\start-local-test-stack.ps1" -RepoRoot "%ROOT%" -OpenBrowser
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo [ERROR] Local test stack did not start. Exit code: %EXIT_CODE%
  if /I not "%IZO_NO_PAUSE%"=="1" pause
)

exit /b %EXIT_CODE%
