@echo off
REM Live log tailer for Docker containers
REM Continuously updates log files every 5 seconds

SET BASE_LOG_DIR=..\src\logs

echo Starting live log tailer...
echo Logs will be updated every 5 seconds
echo Press Ctrl+C to stop
echo.

:LOOP
    REM InfluxDB logs
    docker logs influxdb > "%BASE_LOG_DIR%\influxdb\influxdb.log" 2>&1

    REM Grafana logs
    docker logs grafana > "%BASE_LOG_DIR%\grafana\grafana.log" 2>&1

    REM Wait 5 seconds
    timeout /t 5 /nobreak > nul

    REM Loop forever
    goto LOOP
