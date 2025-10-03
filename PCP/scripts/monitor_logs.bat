@echo off
REM Continuous log monitoring script for Windows
REM This will collect logs every 30 seconds

echo === Starting Continuous Log Collection ===
echo Press Ctrl+C to stop
echo.

:loop
call collect_logs.bat
echo.
echo Waiting 30 seconds before next collection...
timeout /t 30 /nobreak > nul
goto loop
