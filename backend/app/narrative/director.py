"""Narrative Director（M0 版：确定性打分；M2 版：LLM 在合法候选里选）。

无论哪种版本，导演都只做两件事：
1. 判断「现在该不该规划」；
2. 从已过滤的合法候选里挑一个（或都不选）。
它不写状态、不代替角色说话、不决定结局。
"""

from __future__ import annotations

from typing import Any

from .. import game_state as gs
from .storylets import Storylet, StoryletLibrary

# 越晚越该收束的目标
_CLOSING_GOALS = {"clarify_misunderstanding", "discuss_class_change", "define_relationship"}


def should_plan(state: dict[str, Any], reason: str) -> tuple[bool, str]:
    """返回 (是否规划, 原因)。

    M2 把触发收紧：日常闲聊不规划，导演只在「事件刚收尾 / 主动推进 / 临近收尾 /
    连续几轮没有事件」时介入，避免每轮多一次模型调用与额外等待。
    """
    if state["ending_phase"] in ("prepared", "committed"):
        return False, "结局已进入准备或提交阶段"
    if state["active_storylet"]:
        return False, "当前事件仍在进行"
    if state["scheduled_storylet"]:
        return False, "已有待触发事件"
    if state["ending_phase"] == "eligible":
        return True, "进入收束阶段"
    if reason in ("storylet_resolved", "advance"):
        return True, reason
    if gs.progress(state) >= int(state["budget"]["soft_end_at"]):
        return True, "接近结尾预算"
    last_plan = int(state.get("last_plan_turn", -1))
    if state["turn_index"] - last_plan >= 3 and gs.progress(state) >= 3:
        return True, "连续几轮没有事件"
    return False, "节奏未到"


def score(state: dict[str, Any], storylet: Storylet) -> int:
    """确定性评分：只用于 M0 / 兜底。分数可解释、可复核。"""
    s = storylet.priority
    goal_status = state["narrative_goals"].get(storylet.narrative_goal, "pending")
    s += {"pending": 6, "in_progress": 10, "done": -60, "failed": -60}.get(goal_status, 0)

    if storylet.id == "school_gate_finale":
        s += 60
    if gs.near_end(state):
        if storylet.narrative_goal in _CLOSING_GOALS:
            s += 14
        else:
            s -= 25
    if storylet.id in set(state.get("used_storylets") or []):
        s -= 1000
    return s


def propose(state: dict[str, Any], eligible: list[Storylet]) -> Storylet | None:
    if not eligible:
        return None
    ranked = sorted(eligible, key=lambda st: (-score(state, st), st.id))
    return ranked[0]
