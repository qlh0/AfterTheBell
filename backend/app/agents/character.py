"""角色 Agent 入口：M0 用模板，M1 换 LLM，上层调用方式不变。

M1 的 LLM 版必须遵守同一份契约：
- 只输出 JSON：{"dialogue": str, "emotion": enum, "actions": [白名单动作], "storylet_outcome": str|null}
- 动作与结果都会经过规则校验；不合法的部分被丢弃，不写库。
"""

from __future__ import annotations

from typing import Any

from .. import config
from ..narrative.storylets import Storylet
from ..rules.meaningful_turn import Analysis
from . import mock_character
from .mock_character import AgentReply


def reply(
    state: dict[str, Any],
    analysis: Analysis,
    storylet: Storylet | None,
    expected_ending: str | None = None,
    db: Any = None,
    game_id: str | None = None,
) -> AgentReply:
    if config.LLM_MODE == "llm" and config.llm_configured():
        try:
            from .llm_character import llm_reply

            return llm_reply(state, analysis, storylet, expected_ending, db=db, game_id=game_id)
        except Exception as exc:  # 网络/格式失败都必须兜底，界面不能卡死
            fallback = mock_character.reply(state, analysis, storylet, expected_ending)
            fallback.source = f"fallback:{type(exc).__name__}"
            fallback.error = f"{type(exc).__name__}: {exc}"
            return fallback
    return mock_character.reply(state, analysis, storylet, expected_ending)
