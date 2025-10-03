@echo off
REM Script to collect Docker container logs to src/logs directory
REM Each container logs are saved in their own subdirectory with simple names

SET BASE_LOG_DIR=..\src\logs

echo === Docker Container Log Collection ===
echo Timestamp: %date% %time%
echo.

REM Collect logs from influxdb
echo Collecting logs from influxdb...
SET LOG_DIR=%BASE_LOG_DIR%\influxdb
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
docker logs influxdb > "%LOG_DIR%\influxdb.log" 2>&1
echo   Saved to %LOG_DIR%\influxdb.log

REM Collect logs from grafana
echo Collecting logs from grafana...
SET LOG_DIR=%BASE_LOG_DIR%\grafana
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
docker logs grafana > "%LOG_DIR%\grafana.log" 2>&1
echo   Saved to %LOG_DIR%\grafana.log

REM Collect logs from pcp_parser
echo Collecting logs from pcp_parser...
SET LOG_DIR=%BASE_LOG_DIR%\pcp_parser
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
docker logs pcp_parser > "%LOG_DIR%\pcp_parser.log" 2>&1
echo   Saved to %LOG_DIR%\pcp_parser.log

echo.
echo === Log Collection Complete ===
echo Logs saved to: %BASE_LOG_DIR%\
echo.

REM Show log files
echo Log files:
dir "%BASE_LOG_DIR%\influxdb\influxdb.log" 2>nul | findstr /C:".log"
dir "%BASE_LOG_DIR%\grafana\grafana.log" 2>nul | findstr /C:".log"
dir "%BASE_LOG_DIR%\pcp_parser\pcp_parser.log" 2>nul | findstr /C:".log"
