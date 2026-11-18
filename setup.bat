@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1

echo ============================================
echo   After the Bell - environment setup
echo ============================================

py -3.12 "tools\setup_env.py"
if errorlevel 1 python "tools\setup_env.py"
if errorlevel 1 (
    echo.
    echo [ERROR] Setup failed.
    echo Install Python 3.12 from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo.
pause
endlocal
