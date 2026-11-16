"""结局引擎：eligible → prepared → committed。

硬约束：
- 不按单一好感度判定恋爱；
- 结局由「双方实际意愿 + 已达成的事实」决定；
- 收束之前先由状态机给出资格，再由 finale 事件完成最后一次交流。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from .. import game_state as gs
from . import preconditions


@dataclass
class EndingResolution:
    ending_id: str
    changes: list[dict[str, Any]] = field(default_factory=list)
    failed_goals: list[str] = field(default_factory=list)


def finale_eligible(state: dict[str, Any]) -> bool:
    if state["facts"].get("finale_resolved"):
        return False
    if state["scene"] != "school_gate":
        return False
    budget = state["budget"]
    p = gs.progress(state)
    if p >= int(budget["soft_end_at"]) or p >= int(budget["hard_end_at"]):
        return True
    # 三条主线都已经真正碰过，且已经聊过一阵：允许提前收束
    facts = state["facts"]
    ready = (
        facts["misunderstanding_discussed"]
        and facts["class_change_discussed"]
        and facts["player_expressed_romance"]
    )
    return ready and p >= 6


def maybe_make_eligible(state: dict[str, Any]) -> bool:
    if state["ending_phase"] != "none":
        return False
    if not finale_eligible(state):
        return False
    state["ending_phase"] = "eligible"
    return True


def prepare(state: dict[str, Any]) -> None:
    if state["ending_phase"] in ("none", "eligible"):
        state["ending_phase"] = "prepared"


def _romance_ready(state: dict[str, Any]) -> bool:
    rel = state["relationship"]
    facts = state["facts"]
    return (
        facts["misunderstanding_resolved"]
        and facts["class_change_discussed"]
        and facts["player_expressed_romance"]
        and rel["trust"] >= 60
        and rel["respect_for_autonomy"] >= 55
    )


def decide_mutual_intent(state: dict[str, Any]) -> str:
    """她自己的答复：由规则根据已提交的事实决定，不由模型说了算。"""
    rel = state["relationship"]
    facts = state["facts"]
    if facts["player_expressed_romance"]:
        if _romance_ready(state):
            return "romance"
        if rel["respect_for_autonomy"] < 40 or rel["trust"] < 38:
            return "declined"
        return "friendship"
    if rel["respect_for_autonomy"] < 35 or rel["trust"] < 38:
        return "declined"
    if facts["misunderstanding_discussed"] and rel["trust"] >= 40:
        return "friendship"
    return "unknown"


def pick_ending(state: dict[str, Any], content: Any) -> str:
    for ending_id in content.ending_order:
        gates = content.ending(ending_id)["gates"]
        if preconditions.evaluate(gates, state):
            return ending_id
    return "missed"


def preview_ending(state: dict[str, Any], content: Any) -> str:
    """不改真实状态，只推演「如果现在收尾会是哪个结局」，用于角色最后一句的语气。"""
    probe = copy.deepcopy(state)
    probe["facts"]["finale_resolved"] = True
    probe["narrative_goals"]["define_relationship"] = "done"
    probe["npc"]["mutual_intent"] = decide_mutual_intent(probe)
    return pick_ending(probe, content)


def resolve(state: dict[str, Any], content: Any) -> EndingResolution:
    changes: list[dict[str, Any]] = []

    intent = decide_mutual_intent(state)
    if state["npc"]["mutual_intent"] != intent:
        changes.append({
            "path": "npc.mutual_intent",
            "before": state["npc"]["mutual_intent"],
            "after": intent,
            "reason": "finale",
        })
        state["npc"]["mutual_intent"] = intent

    if not state["facts"].get("finale_resolved"):
        state["facts"]["finale_resolved"] = True
        changes.append({
            "path": "facts.finale_resolved",
            "before": False,
            "after": True,
            "reason": "finale",
        })

    if state["narrative_goals"].get("define_relationship") != "done":
        changes.append({
            "path": "narrative_goals.define_relationship",
            "before": state["narrative_goals"].get("define_relationship"),
            "after": "done",
            "reason": "finale",
        })
        state["narrative_goals"]["define_relationship"] = "done"

    ending_id = pick_ending(state, content)

    failed: list[str] = []
    for goal_id, status in list(state["narrative_goals"].items()):
        if status != "done":
            state["narrative_goals"][goal_id] = "failed"
            failed.append(goal_id)

    state["ending_phase"] = "committed"
    state["ending_id"] = ending_id
    state["active_storylet"] = None
    state["storylet_started_turn"] = None
    changes.append({
        "path": "ending_phase",
        "before": "prepared",
        "after": "committed",
        "reason": f"ending:{ending_id}",
    })
    return EndingResolution(ending_id=ending_id, changes=changes, failed_goals=failed)


def ending_block(state: dict[str, Any], content: Any) -> dict[str, Any]:
    spec = content.ending(state["ending_id"])
    return {
        "id": spec["id"],
        "title": spec["title"],
        "subtitle": spec.get("subtitle", ""),
        "epilogue": list(spec.get("epilogue", [])),
        "closing_line": spec.get("closing_line", ""),
    }
