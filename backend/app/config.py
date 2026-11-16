"""运行时配置：路径、端口、LLM 开关。

原则：API 密钥只从环境变量 / .env 读取，永不写入代码、日志或响应。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # D:\AfterTheBell

# .env 只在本机读取；不存在时静默跳过（M0 全部走 mock）。
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:  # pragma: no cover - 缺少 dotenv 时不影响运行
    pass

BACKEND_DIR = ROOT / "backend"
CONTENT_DIR = Path(os.environ.get("ATB_CONTENT_DIR", ROOT / "content"))
DATA_DIR = Path(os.environ.get("ATB_DATA_DIR", BACKEND_DIR / "data"))
PROMPTS_DIR = CONTENT_DIR / "prompts"

DB_PATH = Path(os.environ.get("ATB_DB_PATH", DATA_DIR / "after_the_bell.db"))

HOST = os.environ.get("ATB_HOST", "127.0.0.1")
PORT = int(os.environ.get("ATB_PORT", "8756"))

# mock: 不联网，用模板对白（M0 默认）
# llm:  调用 OpenAI 兼容接口（M1）
LLM_MODE = os.environ.get("ATB_LLM_MODE", "mock").strip().lower()

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
LLM_TIMEOUT_SECONDS = float(os.environ.get("LLM_TIMEOUT_SECONDS", "30"))
LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "1"))
LLM_MAX_OUTPUT_TOKENS = int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "400"))

DIRECTOR_ENABLED = os.environ.get("ATB_DIRECTOR", "0").strip() == "1"

DEFAULT_MEANINGFUL_TURN_BUDGET = int(os.environ.get("ATB_TURN_BUDGET", "12"))


@dataclass(frozen=True)
class Limits:
    """玩家输入与上下文的硬限制，防止 prompt 被灌爆。"""

    player_text_max_chars: int = 300
    history_turns_for_prompt: int = 8
    memories_for_prompt: int = 6
    max_committed_changes: int = 24


LIMITS = Limits()


def llm_configured() -> bool:
    return bool(LLM_API_KEY) and LLM_MODE == "llm"


@dataclass
class RuntimeInfo:
    llm_mode: str = field(default_factory=lambda: LLM_MODE)
    llm_model: str = field(default_factory=lambda: LLM_MODEL)
    director_enabled: bool = field(default_factory=lambda: DIRECTOR_ENABLED)
