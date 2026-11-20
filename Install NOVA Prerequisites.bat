@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-NOVA-Prerequisites.ps1"
if errorlevel 1 (
  echo.
  echo Prerequisite installation failed. Read the error above.
  pause
  exit /b 1
)
echo.
pause
