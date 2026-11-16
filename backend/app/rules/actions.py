"""动作白名单与效果提交。

规则：LLM / Mock 只能「提议动作」，效果由这里决定，并按每回合上限截断。
任何未在白名单里的动作都会被丢弃（并记入 note），不会写进状态。
"""

from __future__ import annotations

from typing import Any

from .. import game_state as gs

# 每个动作固定的状态效果。数值是「单次提议」的量，实际提交还会做每回合上限。
ACTIONS: dict[str, dict[str, Any]] = {
    "ask_distance": {
        "label": "追问最近的疏远",
        "relationship": {"trust": 2, "affection": 1},
        "facts": ["player_asked_distance"],
    },
    "clarify_quote": {
        "label": "把话头引向那句话/误会",
        "relationship": {"trust": 3},
        "facts": ["misunderstanding_discussed"],
    },
    "explain_own_words": {
        "label": "解释自己那句话的真实意思",
        "relationship": {"trust": 4, "respect_for_autonomy": 2},
        "facts": ["misunderstanding_discussed"],
    },
    "ask_chenyu": {
        "label": "提起陈屿",
        "relationship": {"trust": 1},
        "facts": ["chenyu_mentioned"],
    },
    "care": {
        "label": "关心她",
        "relationship": {"trust": 2, "affection": 2},
        "facts": [],
    },
    "apology": {
        "label": "道歉",
        "relationship": {"trust": 3, "affection": 1},
        "facts": [],
    },
    "support_autonomy": {
        "label": "支持她自己的选择",
        "relationship": {"respect_for_autonomy": 4, "trust": 2},
        "facts": ["class_change_discussed"],
    },
    "control_autonomy": {
        "label": "替她做决定",
        "relationship": {"respect_for_autonomy": -7, "trust": -3},
        "facts": ["player_controlling", "class_change_discussed"],
    },
    "express_romance": {
        "label": "明确表达心意",
        "relationship": {"affection": 4},
        "facts": ["player_expressed_romance"],
    },
    "promise": {
        "label": "给出承诺",
        "relationship": {"trust": 2},
        "facts": ["player_promised"],
    },
    "small_talk": {
        "label": "闲聊",
        "relationship": {"affection": 1},
        "facts": [],
    },
    "leave": {
        "label": "表示要走",
        "relationship": {},
        "facts": [],
    },
}

# 单回合每个关系字段的变化上限（正负对称），防止一句话刷爆数值。
PER_TURN_CAP = 9


def commit_actions(
    state: dict[str, Any], actions: list[str], reason: str = ""
) -> tuple[list[dict[str, Any]], list[str]]:
    """按白名单提交动作效果，返回 (changes, notes)。"""
    notes: list[str] = []
    totals: dict[str, int] = {}
    facts: list[str] = []

    for action in dict.fromkeys(actions):  # 去重保序
        spec = ACTIONS.get(action)
        if spec is None:
            notes.append(f"ignored_unknown_action:{action}")
            continue
        for field, amount in spec.get("relationship", {}).items():
            totals[field] = totals.get(field, 0) + int(amount)
        for fact in spec.get("facts", []):
            facts.append(fact)

    capped = {k: max(-PER_TURN_CAP, min(PER_TURN_CAP, v)) for k, v in totals.items()}
    changes = gs.apply_relationship_delta(state, capped, reason or "dialogue")
    changes += gs.apply_fact_changes(state, facts, reason or "dialogue")
    return changes, notes


def record_goal_progress(state: dict[str, Any]) -> list[dict[str, Any]]:
    """根据事实推进叙事目标状态（只前进，不回退；failed 由结局阶段单独处理）。"""
    goals = state["narrative_goals"]
    facts = state["facts"]
    changes: list[dict[str, Any]] = []

    def advance(goal_id: str, status: str) -> None:
        if goal_id not in goals:
            return
        order = {"pending": 0, "in_progress": 1, "done": 2, "failed": 3}
        if order[status] <= order[goals[goal_id]]:
            return
        before = goals[goal_id]
        goals[goal_id] = status
        changes.append({
            "path": f"narrative_goals.{goal_id}",
            "before": before,
            "after": status,
            "reason": "goal_progress",
        })

    if facts["distance_noticed"] or facts["player_asked_distance"]:
        advance("notice_distance", "done")
    if facts["misunderstanding_resolved"]:
        advance("clarify_misunderstanding", "done")
    elif facts["misunderstanding_discussed"]:
        advance("clarify_misunderstanding", "in_progress")
    if facts["class_change_discussed"]:
        advance("discuss_class_change", "done")
    if facts["finale_resolved"]:
        advance("define_relationship", "done")

    return changes
