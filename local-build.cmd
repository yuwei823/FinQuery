@echo off
setlocal
title FinQuery - Local Build
cd /d "%~dp0"

echo [FinQuery] Building local backend and frontend images...

if not exist ".env.docker" (
    echo [ERROR] Missing %CD%\.env.docker
    goto :failed
)

docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker Desktop is not running or is not accessible.
    goto :failed
)

docker compose --env-file .env.docker build --pull=false backend frontend
if errorlevel 1 goto :failed

echo [FinQuery] Synchronizing frontend dependencies into the named volume...
docker compose --env-file .env.docker run --rm --no-deps frontend npm ci
if errorlevel 1 goto :failed

echo.
echo [SUCCESS] Local images and frontend dependencies are ready.
echo Run local-recreate.cmd to recreate the containers.
goto :finished

:failed
echo.
echo [FAILED] Local build stopped. Containers were not recreated.
pause
exit /b 1

:finished
pause
exit /b 0
