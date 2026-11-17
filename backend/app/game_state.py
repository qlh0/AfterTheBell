"""游戏状态：唯一权威数据结构 + 路径读写 + 效果提交。

设计要点：
- 状态以 dict 为规范形态（便于 dotted path 校验），进出边界用 Pydantic 校验。
- 所有数值都有上下限，任何效果不能把状态改成非法值。
- 只允许白名单路径被修改，防止 LLM / 规则写坏结构。
"""

from __future__ import annotations

import json
from typing import Any

from .config import LIMITS

SCENES = ("classroom", "school_gate")
EMOTIONS = ("guarded", "normal", "relieved", "happy", "hurt", "sad", "annoyed", "soft")
MUTUAL_INTENTS = ("unknown", "romance", "friendship", "declined")
PHASES = ("none", "eligible", "prepared", "committed")

GOAL_STATUSES = ("skipped", "pending", "in_progress", "done", "failed")

RELATIONSHIP_FIELDS = ("affection", "trust", "respect_for_autonomy")
RELATIONSHIP_MIN = 0
RELATIONSHIP_MAX = 100

# 可被规则/效果修改的事实白名单（其余字段一律不可写）。
FACT_FIELDS = (
    "class_change_considered",
    "player_knows_class_change",
    "misunderstanding_discussed",
    "misunderstanding_resolved",
    "class_change_discussed",
    "player_expressed_romance",
    "player_declined_romance",
    "player_chose_friends",
    "player_asked_distance",
    "distance_noticed",
    "chenyu_mentioned",
    "chenyu_hint_seen",
    "old_note_seen",
    "player_controlling",
    "player_promised",
    "walk_home_done",
    "finale_resolved",
)

EMOTION_TO_SPRITE = {
    "guarded": "xuzhi_guarded",
    "normal": "xuzhi_normal",
    "relieved": "xuzhi_smile",
    "happy": "xuzhi_smile",
    "soft": "xuzhi_smile",
    "hurt": "xuzhi_guarded",
    "sad": "xuzhi_guarded",
    "annoyed": "xuzhi_guarded",
}


def default_state(game_id: str, goals: list[str], budget: int = 12) -> dict[str, Any]:
    return {
        "game_id": game_id,
        "branch_id": "main",
        "state_version": 0,
        "scene": "classroom",
        "time_slot": "after_school",
        "turn_index": 0,
        "meaningful_turns": 0,
        "relationship": {"affection": 50, "trust": 45, "respect_for_autonomy": 50},
        "facts": {
            "class_change_considered": True,
            "player_knows_class_change": False,
            "misunderstanding_discussed": False,
            "misunderstanding_resolved": False,
            "class_change_discussed": False,
            "player_expressed_romance": False,
            "player_declined_romance": False,
            "player_chose_friends": False,
            "player_asked_distance": False,
            "distance_noticed": False,
            "chenyu_mentioned": False,
            "chenyu_hint_seen": False,
            "old_note_seen": False,
            "player_controlling": False,
            "player_promised": False,
            "walk_home_done": False,
            "finale_resolved": False,
        },
        "npc": {
            "id": "xuzhi",
            "current_emotion": "guarded",
            "personal_goal": "apply_for_advanced_science_class",
            "mutual_intent": "unknown",
        },
        "narrative_goals": {gid: "pending" for gid in goals},
        "open_threads": [],
        "active_storylet": None,
        "storylet_started_turn": None,
        "storylet_stage": "none",       # none | active | interacting
        "storylet_evidence": {},
        "storylet_turns": 0,
        "resolved_storylets": [],
        "abandoned_storylets": [],
        "scheduled_storylet": None,
        "scheduled_at_version": None,
        "last_plan_turn": -1,
        "used_storylets": [],
        "ending_phase": "none",
        "ending_id": None,
        "budget": {
            "max_meaningful_turns": budget,
            "soft_end_at": max(6, budget - 3),
            "hard_end_at": budget + 3,
        },
    }


def clamp(value: int, lo: int = RELATIONSHIP_MIN, hi: int = RELATIONSHIP_MAX) -> int:
    return max(lo, min(hi, int(value)))


def get_path(state: dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = state
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def set_path(state: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = state
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def apply_relationship_delta(state: dict[str, Any], deltas: dict[str, int], reason: str) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    rel = state["relationship"]
    for field, amount in deltas.items():
        if field not in RELATIONSHIP_FIELDS or not amount:
            continue
        before = int(rel.get(field, 0))
        after = clamp(before + int(amount))
        if after == before:
            continue
        rel[field] = after
        changes.append({"path": f"relationship.{field}", "before": before, "after": after, "reason": reason})
    return changes


def apply_fact_changes(state: dict[str, Any], facts: list[str], reason: str) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for fact in facts:
        if fact not in FACT_FIELDS:
            continue
        before = bool(state["facts"].get(fact, False))
        if before:
            continue
        state["facts"][fact] = True
        changes.append({"path": f"facts.{fact}", "before": False, "after": True, "reason": reason})
    return changes


def trim_changes(changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(changes) <= LIMITS.max_committed_changes:
        return changes
    return changes[: LIMITS.max_committed_changes]


def progress(state: dict[str, Any]) -> int:
    """节奏推进量：有效互动优先，但纯闲聊也会推进（一半速度），保证故事不会无限拖。"""
    return max(int(state["meaningful_turns"]), int(state["turn_index"]) // 2)


def near_end(state: dict[str, Any]) -> bool:
    budget = state["budget"]
    return progress(state) >= int(budget["soft_end_at"])


def derive_emotion(state: dict[str, Any]) -> str:
    rel = state["relationship"]
    facts = state["facts"]
    if rel["respect_for_autonomy"] < 35:
        return "hurt"
    if state["ending_phase"] == "committed" or facts["finale_resolved"]:
        return "soft"
    if facts["misunderstanding_resolved"]:
        return "relieved"
    if rel["affection"] >= 66 and rel["trust"] >= 55:
        return "soft"
    if rel["trust"] >= 52 and facts["class_change_discussed"]:
        return "happy"
    if rel["trust"] < 38:
        return "guarded"
    return "normal"


def sprite_for(emotion: str) -> str:
    return EMOTION_TO_SPRITE.get(emotion, "xuzhi_normal")


def dump_state(state: dict[str, Any]) -> str:
    return json.dumps(state, ensure_ascii=False, separators=(",", ":"))


def load_state(raw: str) -> dict[str, Any]:
    return json.loads(raw)


def validate_state(state: dict[str, Any]) -> None:
    """结构性自检：只检查必须存在的键与枚举，避免脏写扩散。"""
    needed = ("game_id", "state_version", "scene", "relationship", "facts", "npc", "narrative_goals", "budget")
    for key in needed:
        if key not in state:
            raise ValueError(f"state 缺少字段: {key}")
    if state["scene"] not in SCENES:
        raise ValueError(f"非法 scene: {state['scene']}")
    if state["npc"].get("mutual_intent") not in MUTUAL_INTENTS:
        raise ValueError(f"非法 mutual_intent: {state['npc'].get('mutual_intent')}")
    if state["ending_phase"] not in PHASES:
        raise ValueError(f"非法 ending_phase: {state['ending_phase']}")
    for field in RELATIONSHIP_FIELDS:
        v = state["relationship"].get(field)
        if not isinstance(v, int) or not (RELATIONSHIP_MIN <= v <= RELATIONSHIP_MAX):
            raise ValueError(f"relationship.{field} 越界: {v!r}")
    for gid, status in state["narrative_goals"].items():
        if status not in GOAL_STATUSES:
            raise ValueError(f"goal {gid} 状态非法: {status}")
