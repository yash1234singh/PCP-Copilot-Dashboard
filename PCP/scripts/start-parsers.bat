@echo off
REM PCP Parser Starter Script for Windows
REM Reads .env file and starts only enabled parsers

setlocal enabledelayedexpansion

echo Loading configuration from .env...
echo.

REM Check if .env exists
if not exist .env (
    echo ERROR: .env file not found!
    exit /b 1
)

REM Read .env file and set variables
for /f "usebackq tokens=1,2 delims==" %%a in (.env) do (
    REM Skip comments
    echo %%a | findstr /r "^#" >nul
    if errorlevel 1 (
        set %%a=%%b
    )
)

REM Build profiles based on configuration
set PROFILES=
set PROFILE_COUNT=0

if /i "%ENABLE_PYTHON_PARSER%"=="true" (
    set PROFILES=!PROFILES! --profile python-parser
    set /a PROFILE_COUNT+=1
    echo [32m√ Python parser enabled[0m
) else (
    echo [31m× Python parser disabled[0m
)

if /i "%ENABLE_GO_PARSER%"=="true" (
    set PROFILES=!PROFILES! --profile go-parser
    set /a PROFILE_COUNT+=1
    echo [32m√ Go parser enabled[0m
) else (
    echo [31m× Go parser disabled[0m
)

if /i "%ENABLE_RUST_PARSER%"=="true" (
    set PROFILES=!PROFILES! --profile rust-parser
    set /a PROFILE_COUNT+=1
    echo [32m√ Rust parser enabled[0m
) else (
    echo [31m× Rust parser disabled[0m
)

echo.

REM Check if at least one parser is enabled
if %PROFILE_COUNT%==0 (
    echo [31mERROR: No parsers enabled![0m
    echo.
    echo Please set at least one parser to 'true' in .env file:
    echo   ENABLE_PYTHON_PARSER=true
    echo   ENABLE_GO_PARSER=true
    echo   ENABLE_RUST_PARSER=true
    echo.
    exit /b 1
)

echo Starting containers with selected parsers...
echo Command: docker-compose%PROFILES% up -d
echo.

REM Start docker-compose with selected profiles
docker-compose%PROFILES% up -d

if errorlevel 1 (
    echo [31mERROR: Failed to start containers![0m
    exit /b 1
)

echo.
echo [32m√ Started successfully![0m
echo.
echo Running containers:
docker ps --filter "name=pcp_parser" --format "table {{.Names}}\t{{.Status}}"

endlocal
