@echo off
setlocal
title FinQuery - Production Recreate
cd /d "%~dp0"

echo [FinQuery] Recreating production backend and public gateway containers...

if not exist ".env.public" (
    echo [ERROR] Missing %CD%\.env.public
    goto :failed
)

docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker Desktop is not running or is not accessible.
    goto :failed
)

docker compose --env-file .env.public --profile public-preview up -d --no-build --force-recreate backend-public public-gateway
if errorlevel 1 goto :failed

docker compose --env-file .env.public --profile public-preview ps
if errorlevel 1 goto :failed

echo.
echo [SUCCESS] Production containers were recreated.
echo Preview: http://127.0.0.1:8080/
echo Cloudflared was not recreated.
goto :finished

:failed
echo.
echo [FAILED] Production recreate did not complete.
pause
exit /b 1

:finished
pause
exit /b 0
