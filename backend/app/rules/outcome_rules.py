"""事件结果的「规则默认值」。

用途有两个：
1. 没有 LLM（M0）或 LLM 没给结果时，用它决定事件走向；
2. 内容自检时，确认每个事件至少有一个人可推导的默认结局。

它只读取玩家这一回合实际说的话（Analysis），不看模型。
"""

from __future__ import annotations

from ..narrative.storylets import Storylet
from .meaningful_turn import Analysis


def default_outcome(storylet: Storylet, analysis: Analysis) -> str:
    outcomes = storylet.possible_outcomes
    first = outcomes[0] if outcomes else "resolved"

    if storylet.id == "late_explanation":
        if analysis.controlling:
            return "worse"
        if "explain_own_words" in analysis.actions:
            return "clarified"
        return "partially_clarified"

    if storylet.id == "class_choice":
        if analysis.controlling or "control_autonomy" in analysis.actions:
            return "conflict_emerged"
        # 只有真的把话题落在「分班/她自己的打算」上，才算认真谈过；
        # 玩家突然转去表白，不算谈过分班。
        if "support_autonomy" in analysis.actions or analysis.topics & {"class_change", "care"}:
            return "discussed_respectfully"
        return "topic_avoided"

    if storylet.id == "walk_home":
        if "leave" in analysis.topics and not (analysis.topics & {"romance", "misunderstanding", "class_change"}):
            return "walked_apart"
        if analysis.topics & {"romance", "misunderstanding", "class_change", "distance"}:
            return "walked_and_talked"
        return "walked_together"

    if storylet.id == "old_note":
        if analysis.controlling:
            return "distance_kept"
        if analysis.topics & {"distance", "romance", "care", "misunderstanding"}:
            return "nostalgia_shared"
        return "topic_avoided"

    if storylet.id == "direct_question":
        if analysis.topics & {"distance", "misunderstanding", "care"}:
            return "admitted_distance"
        if analysis.topics & {"class_change", "chenyu"}:
            return "partial_truth"
        return "deflected"

    if storylet.id == "chenyu_hint":
        if "chenyu" in analysis.topics:
            return "hint_received"
        if analysis.topics & {"distance", "misunderstanding"}:
            return "topic_dropped"
        return "suspicion_raised"

    if storylet.id == "library_study":
        if "leave" in analysis.topics:
            return "left_early"
        if any(w in analysis.normalized for w in ("学习", "题", "作业", "看书")):
            return "studied_together"
        return "studied_quietly"

    if storylet.id == "corridor_chat":
        if "leave" in analysis.topics:
            return "interrupted"
        if analysis.topics & {"distance", "misunderstanding", "class_change", "romance", "care"}:
            return "chatted"
        return "awkward"

    if storylet.id == "shop_trip":
        if "chenyu" in analysis.topics:
            return "ran_into_classmate"
        if any(w in analysis.normalized for w in ("买", "喝", "吃", "零食")):
            return "bought_together"
        return "went_alone"

    return first
