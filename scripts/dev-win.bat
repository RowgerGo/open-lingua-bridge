@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PS_SCRIPT=%SCRIPT_DIR%dev-win.ps1"

if not exist "%PS_SCRIPT%" (
  echo PowerShell script not found: %PS_SCRIPT%
  pause
  exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo dev-win.ps1 exited with code %EXIT_CODE%.
  pause
)

exit /b %EXIT_CODE%
