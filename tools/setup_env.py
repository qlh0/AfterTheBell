#!/usr/bin/env python3
"""创建 .venv 并安装后端依赖（跨平台）。

Windows:  setup.bat
macOS:    setup.command
"""

from __future__ import annotations

import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = ROOT / ".venv"
REQUIREMENTS = ROOT / "backend" / "requirements.txt"


def venv_python() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def main() -> int:
    print("=" * 52)
    print("  After the Bell - environment setup")
    print("=" * 52)
    print(f"Python: {sys.version.split()[0]}  ({sys.executable})")

    if sys.version_info < (3, 12):
        print("\n[ERROR] Python 3.12+ is required.")
        print("Download: https://www.python.org/downloads/")
        return 1

    if not VENV_DIR.exists():
        print("\n[..] Creating .venv ...")
        venv.EnvBuilder(with_pip=True).create(VENV_DIR)
    else:
        print("\n[OK] .venv already exists")

    python = venv_python()
    if not python.exists():
        print(f"\n[ERROR] venv python not found: {python}")
        return 1

    print("[..] Upgrading pip ...")
    subprocess.check_call([str(python), "-m", "pip", "install", "--upgrade", "pip"])
    print("[..] Installing backend requirements ...")
    subprocess.check_call([str(python), "-m", "pip", "install", "-r", str(REQUIREMENTS)])

    print("\n" + "=" * 52)
    print("[OK] Setup finished")
    print("Next steps:")
    print("  1) copy .env.example to .env")
    print("  2) fill LLM_API_KEY (required)")
    print("  3) run run_dev.bat (Windows) / run_dev.command (macOS)")
    print("=" * 52)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
