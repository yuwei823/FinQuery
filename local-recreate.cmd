@echo off
setlocal
title FinQuery - Local Recreate
cd /d "%~dp0"

echo [FinQuery] Recreating local backend and frontend containers...

if not exist ".env.docker" (
    echo [ERROR] Missing %CD%\.env.docker
    goto :failed
)

docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker Desktop is not running or is not accessible.
    goto :failed
)

docker compose --env-file .env.docker up -d --no-build --force-recreate backend frontend
if errorlevel 1 goto :failed

docker compose --env-file .env.docker ps
if errorlevel 1 goto :failed

echo.
echo [SUCCESS] Local containers were recreated.
echo Frontend: http://127.0.0.1:5173/
echo Backend:  http://127.0.0.1:8000/api/health
goto :finished

:failed
echo.
echo [FAILED] Local recreate did not complete.
pause
exit /b 1

:finished
pause
exit /b 0
