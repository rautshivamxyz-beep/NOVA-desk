@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command ^
  "$root = '%~dp0'; $desktop = [Environment]::GetFolderPath('Desktop');" ^
  "$path = Join-Path $desktop 'NOVA Desktop 3.0.lnk';" ^
  "$shell = New-Object -ComObject WScript.Shell; $link = $shell.CreateShortcut($path);" ^
  "$link.TargetPath = Join-Path $root 'Start NOVA.bat';" ^
  "$link.WorkingDirectory = $root; $link.Description = 'Start NOVA Desktop 3.0';" ^
  "$link.IconLocation = Join-Path $env:SystemRoot 'System32\shell32.dll,43'; $link.Save();" ^
  "Write-Host ('Created ' + $path)"
echo.
pause
