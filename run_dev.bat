@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo  《那天放学后》 After the Bell - M0
echo ============================================

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 没有找到 .venv。
    echo 请先执行：py -3.12 -m venv .venv
    echo 然后：.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
    pause
    exit /b 1
)

echo [1/3] 启动后端（独立窗口，关掉那个窗口即可停止后端）...
start "AfterTheBell API" cmd /k "%~dp0run_backend.bat"

echo [2/3] 等待后端就绪...
powershell -NoProfile -Command "for ($i=0; $i -lt 25; $i++) { try { $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8756/health' -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; Start-Sleep -Milliseconds 800 }; exit 1"
if errorlevel 1 (
    echo [警告] 后端 20 秒内没有就绪，仍然尝试启动游戏。
    echo         如果游戏提示连不上后端，看一下那个 API 窗口的报错。
)

echo [3/3] 启动游戏...
set "RENPY_EXE=D:\renpy-8.6.0-sdk\renpy.exe"
if exist "%RENPY_EXE%" (
    start "" "%RENPY_EXE%" "%~dp0"
) else (
    echo [错误] 没找到 Ren'Py SDK: %RENPY_EXE%
    echo         请修改本脚本里的 RENPY_EXE 路径，或用 Ren'Py 启动器打开本目录。
    pause
)

endlocal
