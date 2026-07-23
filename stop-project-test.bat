@echo off
setlocal
chcp 65001 >nul

set "ROOT=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%tools\stop-local-test-stack.ps1" -RepoRoot "%ROOT%"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo [ERROR] Local test stack did not stop cleanly. Exit code: %EXIT_CODE%
  if /I not "%IZO_NO_PAUSE%"=="1" pause
)

exit /b %EXIT_CODE%
