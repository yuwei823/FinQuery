@echo off
setlocal
title FinQuery - Production Build
cd /d "%~dp0"

echo [FinQuery] Building production backend and public gateway images...

if not exist ".env.public" (
    echo [ERROR] Missing %CD%\.env.public
    goto :failed
)

docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker Desktop is not running or is not accessible.
    goto :failed
)

docker compose --env-file .env.public --profile public-preview build --pull=false backend-public public-gateway
if errorlevel 1 goto :failed

echo.
echo [SUCCESS] Production images are ready.
echo Run production-recreate.cmd to publish these images.
goto :finished

:failed
echo.
echo [FAILED] Production build stopped. Existing production containers were not changed.
pause
exit /b 1

:finished
pause
exit /b 0
