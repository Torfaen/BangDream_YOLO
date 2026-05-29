@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1"
set EXIT_CODE=%ERRORLEVEL%

echo.
if not "%EXIT_CODE%"=="0" (
  echo Startup failed, exit code: %EXIT_CODE%
) else (
  echo Startup flow finished.
)
pause
exit /b %EXIT_CODE%
