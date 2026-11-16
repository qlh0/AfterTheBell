@echo off
REM 启动后端（供 run_dev.bat 调用）
setlocal
cd /d "%~dp0backend"
"%~dp0.venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir "%~dp0backend" --host 127.0.0.1 --port 8756
endlocal
