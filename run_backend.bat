@echo off
setlocal
cd /d "%~dp0backend"
chcp 65001 >nul
set PYTHONUTF8=1
"%~dp0.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8756
endlocal
