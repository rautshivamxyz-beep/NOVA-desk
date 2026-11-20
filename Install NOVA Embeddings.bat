@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-NOVA-Embeddings.ps1"
if errorlevel 1 (
  echo.
  pause
  exit /b 1
)
pause
