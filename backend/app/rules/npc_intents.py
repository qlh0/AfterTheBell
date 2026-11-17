"""许栀的主动意图（NPC initiative）。

她可以主动提问、提起分班、邀请同行、划定边界，但：
- 只能从白名单里选；
- 上下文不成立时忽略（比如教室里不会邀请一起走）；
- **主动开口 ≠ 事件完成**：这里只负责把事件排期，结果仍由后续互动证据决定。
"""

from __future__ import annotations

from typing import Any

INTENTS: dict[str, dict[str, Any]] = {
    "ask_about_distance": {
        "label": "主动问玩家最近是不是在疏远",
        "storylet": "direct_question",
        "why": "她感觉到气氛不对，想先开口问清楚",
    },
    "bring_up_class_change": {
        "label": "主动提起分班",
        "storylet": "class_choice",
        "why": "她自己的升学选择一直压在心里",
    },
    "invite_walk_home": {
        "label": "主动邀请一起走",
        "storylet": "walk_home",
        "why": "她愿意给两个人一段并肩的时间",
    },
    "share_memory": {
        "label": "主动提起共同的记忆",
        "storylet": "shared_memory",
        "why": "她想用以前的事缓和现在的距离",
    },
    "set_boundary": {
        "label": "明确划出边界",
        "storylet": None,
        "why": "她不接受被替自己做决定",
    },
    "drop_topic": {
        "label": "主动把话题放下",
        "storylet": None,
        "why": "她不想继续这个方向",
    },
}

WHITELIST = set(INTENTS)


def validate(state: dict[str, Any], intent: str) -> tuple[bool, str]:
    """上下文校验：她会不会在这种情况下主动做这件事。"""
    if intent not in INTENTS:
        return False, "not_in_whitelist"
    facts = state["facts"]
    rel = state["relationship"]

    if intent == "ask_about_distance":
        if facts.get("player_asked_distance") or facts.get("distance_noticed"):
            return False, "distance_already_discussed"
        return True, ""

    if intent == "bring_up_class_change":
        if facts.get("class_change_discussed"):
            return False, "class_already_discussed"
        if state.get("meaningful_turns", 0) < 2:
            return False, "too_early"
        return True, ""

    if intent == "invite_walk_home":
        if state["scene"] != "school_gate":
            return False, "not_at_gate"
        if facts.get("walk_home_done"):
            return False, "already_walked"
        if rel["trust"] < 40:
            return False, "trust_too_low"
        return True, ""

    if intent == "share_memory":
        if not (facts.get("old_note_seen") or facts.get("walk_home_done")):
            return False, "no_shared_memory_yet"
        return True, ""

    if intent == "set_boundary":
        if not (facts.get("player_controlling") or rel["respect_for_autonomy"] < 45):
            return False, "no_boundary_needed"
        return True, ""

    return True, ""


def storylet_for(intent: str) -> str | None:
    return INTENTS.get(intent, {}).get("storylet")


def prompt_lines() -> list[str]:
    return [f"- {key}：{spec['label']}（{spec['why']}）" for key, spec in INTENTS.items()]


def parse(state: dict[str, Any], raw: Any) -> tuple[str | None, str]:
    """把模型输出规范成合法的 npc_intent；不合法返回 (None, 原因)。"""
    if not isinstance(raw, str) or not raw.strip():
        return None, "empty"
    intent = raw.strip()
    ok, why = validate(state, intent)
    return (intent if ok else None), ("" if ok else why)
