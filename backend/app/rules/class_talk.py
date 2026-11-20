"""「分班已经聊过」的识别。

v0.3.1：玩家问到分班、她也真的说了自己的打算（填了/报了理重点班/还不确定），
这一轮就算「谈过分班」，即使当时没有 class_choice 事件在演。

目的：分班只讲一次。谈过之后不再触发 class_choice，也不再让她反复提意向表。
"""

from __future__ import annotations

from typing import Any

from .. import game_state as gs
from .meaningful_turn import Analysis

PLAN_WORDS = (
    "理重点", "重点班", "理科", "文科", "物理", "历史", "方向",
    "报理", "报文", "志愿", "还不确定", "没想好", "在犹豫",
)
DEFLECT_WORDS = (
    "不想说", "别问", "以后再说", "没什么好说", "跟你没关系",
    "随便报", "随便填", "查户口", "问这个干嘛", "关你什么事",
)


def commit(state: dict[str, Any], analysis: Analysis, dialogue: str) -> list[dict[str, Any]]:
    facts = state["facts"]
    if facts.get("class_change_discussed"):
        return []
    if "class_change" not in analysis.topics:
        return []
    text = dialogue or ""
    if any(w in text for w in DEFLECT_WORDS):
        return []
    if not any(w in text for w in PLAN_WORDS):
        return []

    changes = gs.apply_fact_changes(state, ["class_change_discussed"], "class_talk")
    changes += gs.apply_relationship_delta(state, {"trust": 1}, "class_talk")

    # 如果分班事件正在演，把这一轮记为「她说清了计划 + 玩家接住了」
    if state.get("active_storylet") == "class_choice":
        evidence = state.setdefault("storylet_evidence", {})
        evidence["class_plan"] = True
        evidence.setdefault("form_shown", True)
    return changes
