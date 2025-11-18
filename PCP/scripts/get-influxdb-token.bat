@echo off
REM Helper script to display the InfluxDB admin token for Explorer UI setup

set "ENV_FILE=%~dp0..\src\.env"

if not exist "%ENV_FILE%" (
    echo Error: .env file not found at %ENV_FILE%
    echo Run 'docker-compose up -d' first to generate the token
    exit /b 1
)

for /f "tokens=2 delims==" %%a in ('findstr /b "INFLUXDB_TOKEN=" "%ENV_FILE%"') do set TOKEN=%%a

if "%TOKEN%"=="" (
    echo Error: INFLUXDB_TOKEN not found in .env file
    echo Run 'docker-compose up -d' first to generate the token
    exit /b 1
)

echo ==========================================
echo InfluxDB 3 Explorer Configuration
echo ==========================================
echo.
echo Server Name:  influxdb3-server
echo Server URL:   http://host.docker.internal:8181
echo Token:        %TOKEN%
echo.
echo ==========================================
echo Copy the token above and paste it into
echo the Explorer UI at http://localhost:8888
echo ==========================================
pause
