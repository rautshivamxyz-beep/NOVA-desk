@echo off
curl.exe -sS -X POST -H "Content-Type: application/json" -d "{}" http://127.0.0.1:8765/api/quit
if errorlevel 1 echo NOVA is not running or could not be stopped.
echo.
pause
