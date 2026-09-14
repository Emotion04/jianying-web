@echo off
setlocal enabledelayedexpansion
title JianYing Editor Web

echo.
echo ================================================
echo    JianYing Editor Web
echo    JianYing Automation Console
echo ================================================
echo.

:: Detect script location
set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
cd /d "%PROJECT_DIR%"
echo [INFO] Project: %PROJECT_DIR%

:: Find Python - check venv first
set "PYTHON=%PROJECT_DIR%\skills\jianying-editor\.venv\Scripts\python.exe"
if exist "!PYTHON!" (
    echo [OK] Using venv Python
    goto :check_backend
)

:: Fallback: search system Python
echo [WARN] venv not found, searching system Python...
set "PYTHON="
for %%p in (python python3 py) do (
    where %%p >nul 2>nul
    if not errorlevel 1 (
        if "!PYTHON!"=="" set "PYTHON=%%p"
    )
)

if "!PYTHON!"=="" (
    echo [ERROR] Python not found!
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [OK] Using system Python: !PYTHON!

:check_backend
if not exist "%PROJECT_DIR%\backend\main.py" (
    echo [ERROR] backend\main.py not found
    echo Make sure you're running this from the project root
    pause
    exit /b 1
)

:: Verify Python works
"!PYTHON!" --version >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not working: !PYTHON!
    pause
    exit /b 1
)

:: Install deps if needed (suppress all output)
echo [INFO] Checking dependencies...
"!PYTHON!" -c "import fastapi, uvicorn, httpx" >nul 2>nul
if errorlevel 1 (
    echo [INFO] Installing dependencies...
    "!PYTHON!" -m pip install fastapi uvicorn python-multipart aiofiles httpx -q --disable-pip-version-check
)

:: Start
echo.
echo ------------------------------------------------
echo   Server starting...
echo   Local:  http://localhost:8000
echo   LAN:    http://YOUR_IP:8000
echo   Press Ctrl+C to stop
echo ------------------------------------------------
echo.

"!PYTHON!" "%PROJECT_DIR%\backend\main.py"

echo.
echo [INFO] Server stopped
pause
