#!/usr/bin/env python3
"""跨平台本地启动器。

做四件事：
1. 检查 .env / API Key（正式游玩必须配置真实 Key）；
2. 找到 Ren'Py SDK（RENPY_HOME / RENPY_BIN / 常见安装位置）；
3. 启动 FastAPI 后端并等待 /health；
4. 启动 Ren'Py 客户端，退出时关闭由本脚本启动的后端。

用法：
    python tools/dev.py           # 启动
    python tools/dev.py --check   # 只检查环境，不启动
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
ENV_FILE = ROOT / ".env"
PLACEHOLDER_KEYS = {"", "sk-...", "your-api-key", "your_key_here", "changeme"}


def say(message: str = "") -> None:
    print(message, flush=True)


def fail(message: str) -> None:
    print(f"\n[ERROR] {message}\n", file=sys.stderr, flush=True)
    raise SystemExit(1)


def read_env_file() -> dict[str, str]:
    """极简 .env 读取，只用于启动前检查；后端仍用 python-dotenv 读取。"""
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values
    try:
        lines = ENV_FILE.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def env_get(file_env: dict[str, str], key: str, default: str = "") -> str:
    # 真实环境变量优先，其次 .env
    if key in os.environ:
        return os.environ[key]
    return file_env.get(key, default)


def venv_python() -> Path | None:
    candidates = [
        ROOT / ".venv" / "Scripts" / "python.exe",  # Windows
        ROOT / ".venv" / "bin" / "python",          # macOS / Linux
    ]
    return next((p for p in candidates if p.exists()), None)


def _renpy_names() -> list[str]:
    if os.name == "nt":
        return ["renpy.exe", "renpy.bat"]
    return ["renpy.sh", "renpy"]


def _add_candidates(out: list[Path], base: Path) -> None:
    if not base.exists():
        return
    if base.is_file():
        out.append(base)
        return
    for name in _renpy_names():
        out.append(base / name)
    if sys.platform == "darwin":
        out.append(base / "renpy.app" / "Contents" / "MacOS" / "renpy")


def find_renpy() -> Path | None:
    candidates: list[Path] = []

    for key in ("RENPY_BIN", "RENPY_EXE"):
        value = os.environ.get(key, "").strip()
        if value:
            candidates.append(Path(value).expanduser())

    home = os.environ.get("RENPY_HOME", "").strip()
    if home:
        _add_candidates(candidates, Path(home).expanduser())
    _add_candidates(candidates, ROOT / "renpy")
    _add_candidates(candidates, ROOT)

    search_roots = [
        Path.home() / "Downloads",
        Path.home() / "Applications",  # macOS 用户目录
        Path.home(),
        Path("/Applications"),          # macOS
        Path("/opt"),
        Path("/usr/local"),
    ]
    if os.name == "nt":
        for env_name in ("ProgramFiles", "LOCALAPPDATA"):
            value = os.environ.get(env_name, "").strip()
            if value:
                search_roots.append(Path(value) / "Programs")
                search_roots.append(Path(value))
                for name in ("RenPy", "renpy"):
                    _add_candidates(candidates, Path(value) / name)
        # 盘符根目录只匹配 renpy-*，不会全盘扫描
        search_roots.extend([Path("C:/"), Path("D:/")])
    elif sys.platform == "darwin":
        _add_candidates(candidates, Path("/Applications/renpy.app"))
        _add_candidates(candidates, Path.home() / "Applications" / "renpy.app")

    for base in search_roots:
        if not base.exists():
            continue
        try:
            for folder in sorted(base.glob("renpy-*"), reverse=True):
                _add_candidates(candidates, folder)
        except OSError:
            continue

    for command in ("renpy", "renpy.exe", "renpy.sh"):
        found = shutil.which(command)
        if found:
            candidates.append(Path(found))

    seen: set[str] = set()
    for path in candidates:
        try:
            resolved = str(path.resolve())
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if path.is_file():
            return path
    return None


def renpy_command(renpy: Path) -> list[str]:
    if renpy.suffix.lower() == ".sh":
        return ["bash", str(renpy), str(ROOT)]
    return [str(renpy), str(ROOT)]


def check_key(file_env: dict[str, str]) -> str:
    if not ENV_FILE.exists() and "LLM_API_KEY" not in os.environ:
        fail(
            "未找到 .env。\n"
            "  1) 复制 .env.example 为 .env\n"
            "  2) 填写 LLM_API_KEY\n"
            "  Windows: copy .env.example .env\n"
            "  macOS:   cp .env.example .env"
        )

    mode = env_get(file_env, "ATB_LLM_MODE", "llm").strip().lower()
    key = env_get(file_env, "LLM_API_KEY", "").strip()
    allow_mock = env_get(file_env, "ATB_ALLOW_MOCK", "0").strip() == "1"

    if mode == "mock":
        if not allow_mock:
            fail(
                "mock 模式仅供自动化测试/离线开发。\n"
                "正式游玩请把 .env 里的 ATB_LLM_MODE 改为 llm，并填写 LLM_API_KEY。"
            )
        say("[WARN] 当前是 mock 模式：只使用模板对白，不是完整 AI 体验。")
        return mode
    if mode != "llm":
        fail(f"ATB_LLM_MODE 只能是 llm 或 mock，当前：{mode}")
    if key.lower() in PLACEHOLDER_KEYS:
        fail(
            "LLM_API_KEY 还没有填写。\n"
            "  1) 打开 https://platform.deepseek.com/ 创建 API Key\n"
            "  2) 填到项目根目录 .env 的 LLM_API_KEY= 后面\n"
            "  3) 重新运行启动脚本"
        )
    say("[OK] LLM Key 已配置（不会打印到控制台）")
    return mode


def check_prereqs(file_env: dict[str, str]) -> tuple[Path, Path, int]:
    python = venv_python()
    if python is None:
        fail(
            "没有找到 .venv。\n"
            "  Windows: 双击 setup.bat\n"
            "  macOS:   双击 setup.command（或 bash setup.command）"
        )

    probe = subprocess.run(
        [str(python), "-c", "import fastapi, uvicorn, httpx, dotenv"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if probe.returncode != 0:
        fail(
            "Python 依赖不完整。\n"
            "  Windows: 双击 setup.bat\n"
            "  macOS:   双击 setup.command"
        )

    renpy = find_renpy()
    if renpy is None:
        fail(
            "没有找到 Ren'Py SDK（需要 8.6）。\n"
            "  1) 下载：https://www.renpy.org/latest.html\n"
            "  2) 解压/安装后，设置环境变量 RENPY_HOME 指向 SDK 目录，例如：\n"
            "     Windows: set RENPY_HOME=C:\\path\\to\\renpy-8.6.0-sdk\n"
            "     macOS:   export RENPY_HOME=~/renpy-8.6.0-sdk\n"
            "  3) 重新运行启动脚本"
        )

    try:
        port = int(env_get(file_env, "ATB_PORT", "8756"))
    except ValueError:
        fail("ATB_PORT 不是合法端口号。")
    if not (1 <= port <= 65535):
        fail("ATB_PORT 超出范围（1-65535）。")

    say(f"[OK] Ren'Py: {renpy}")
    say(f"[OK] Python: {python}")
    return python, renpy, port


def health_ok(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1.5) as response:
            data = json.loads(response.read().decode("utf-8"))
        return bool(data.get("ok"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return False


def start_backend(python: Path, port: int) -> subprocess.Popen | None:
    if health_ok(port):
        say(f"[OK] 后端已在运行：http://127.0.0.1:{port}")
        return None

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    command = [
        str(python),
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    say(f"[..] 启动后端：http://127.0.0.1:{port}")
    process = subprocess.Popen(command, cwd=str(BACKEND), env=env)

    deadline = time.time() + 30
    while time.time() < deadline:
        if process.poll() is not None:
            fail(
                "后端启动失败（进程已退出）。\n"
                "常见原因：LLM_API_KEY 未填、端口被占用、依赖未安装。请查看上方报错。"
            )
        if health_ok(port):
            say("[OK] 后端已就绪")
            return process
        time.sleep(0.5)

    process.terminate()
    fail("后端 30 秒内没有就绪。请检查 API Key、端口和终端报错。")


def stop_backend(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description="After the Bell local launcher")
    parser.add_argument("--check", action="store_true", help="only check environment")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    say("=" * 52)
    say("  After the Bell / 那天放学后")
    say("=" * 52)
    say(f"项目目录：{ROOT}")

    file_env = read_env_file()
    mode = check_key(file_env)
    python, renpy, port = check_prereqs(file_env)

    if args.check:
        say("")
        say(f"[OK] 检查通过：mode={mode}, port={port}")
        say("[OK] 运行 run_dev 即可开始游戏")
        return 0

    backend = start_backend(python, port)
    try:
        say("[..] 启动 Ren'Py 客户端...")
        return subprocess.call(renpy_command(renpy), cwd=str(ROOT))
    except KeyboardInterrupt:
        say("\n[..] 已中断")
        return 130
    finally:
        stop_backend(backend)


if __name__ == "__main__":
    raise SystemExit(main())
