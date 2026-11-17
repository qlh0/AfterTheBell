"""Storylet 生命周期：active → interacting → resolved / abandoned。

v0.3 的核心修正：事件被引出 ≠ 玩家接受邀请 ≠ 事件已发生。
结果必须来自「可核验的互动证据」，证据不足时事件继续等待；超时才明确放弃，
绝不硬选一个"默认成功"结果。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..narrative.storylets import Storylet
from .meaningful_turn import Analysis

# 事件最多允许几次玩家互动后仍未结算 → 放弃
MAX_TURNS = {
    "old_note": 2,
    "direct_question": 2,
    "chenyu_hint": 2,
    "late_explanation": 3,
    "class_choice": 3,
    "walk_home": 2,
    "shared_memory": 2,
    "unfinished_conversation": 3,
    "school_gate_finale": 3,
}

# 各事件激活时的初始证据
INITIAL_EVIDENCE = {
    "late_explanation": {"quote_raised": True},
    "class_choice": {"form_shown": True},
    "walk_home": {"invitation_made": True},
}

ACCEPT_WORDS = ("一起", "走吧", "好", "行", "可以", "顺路", "陪你", "走一段", "那走")
DECLINE_WORDS = ("不用", "算了", "自己走", "先走", "不必", "不了", "你走吧")
FUTURE_WORDS = ("以后", "未来", "分班后", "见不到", "一起走", "还能", "下学期", "以后还")
PLAN_WORDS = ("报", "考", "决定", "打算", "计划", "想读", "申请", "填")


@dataclass
class Progress:
    outcome: str | None = None
    reason: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


def initial_evidence(storylet: Storylet) -> dict[str, Any]:
    return dict(INITIAL_EVIDENCE.get(storylet.id, {}))


def update_evidence(
    state: dict[str, Any],
    storylet: Storylet,
    analysis: Analysis,
    reply_actions: list[str] | None = None,
) -> dict[str, Any]:
    """从这一轮的玩家文本/动作里累积事件证据。"""
    ev: dict[str, Any] = state.setdefault("storylet_evidence", {})
    text = analysis.normalized
    actions = set(analysis.actions) | set(reply_actions or [])
    topics = analysis.topics
    sid = storylet.id

    if sid == "old_note":
        ev["engaged"] = ev.get("engaged") or bool(
            topics & {"distance", "romance", "care", "misunderstanding"}
            or actions & {"care", "ask_distance", "clarify_quote"}
        )
        ev["cold"] = ev.get("cold") or "control_autonomy" in actions

    elif sid == "direct_question":
        ev["distance_talk"] = ev.get("distance_talk") or bool(
            topics & {"distance", "misunderstanding", "care"})
        ev["partial_talk"] = ev.get("partial_talk") or bool(topics & {"class_change", "chenyu"})

    elif sid == "chenyu_hint":
        ev["chenyu_talk"] = ev.get("chenyu_talk") or "chenyu" in topics
        ev["distance_talk"] = ev.get("distance_talk") or bool(
            topics & {"distance", "misunderstanding"})

    elif sid == "late_explanation":
        ev["quote_discussed"] = ev.get("quote_discussed") or bool(
            "misunderstanding" in topics
            or actions & {"clarify_quote", "explain_own_words"}
            or "那句话" in text
        )
        ev["explanation_offered"] = ev.get("explanation_offered") or "explain_own_words" in actions
        ev["pressure"] = ev.get("pressure") or "control_autonomy" in actions
        ev["apology"] = ev.get("apology") or "apology" in actions

    elif sid == "class_choice":
        ev["class_plan"] = ev.get("class_plan") or bool(
            "class_change" in topics and any(w in text for w in PLAN_WORDS))
        ev["future_talk"] = ev.get("future_talk") or any(w in text for w in FUTURE_WORDS)
        ev["respectful"] = ev.get("respectful") or "support_autonomy" in actions
        ev["pressure"] = ev.get("pressure") or "control_autonomy" in actions

    elif sid == "walk_home":
        if any(w in text for w in DECLINE_WORDS):
            ev["player_declined"] = True
        elif any(w in text for w in ACCEPT_WORDS):
            ev["player_accepted"] = True
        if "leave" in topics and not ev.get("player_accepted"):
            ev["player_declined"] = True

    elif sid == "shared_memory":
        ev["engaged"] = ev.get("engaged") or bool(
            topics & {"romance", "care", "distance"} or any(w in text for w in ("记得", "以前", "那时候")))
        ev["different"] = ev.get("different") or any(w in text for w in ("忘了", "不记得", "没印象"))

    elif sid == "unfinished_conversation":
        ev["feelings"] = ev.get("feelings") or bool(
            topics & {"romance", "misunderstanding", "distance", "care"})
        ev["explanation"] = ev.get("explanation") or "explain_own_words" in actions
        ev["apology"] = ev.get("apology") or "apology" in actions
        ev["pressure"] = ev.get("pressure") or "control_autonomy" in actions

    elif sid == "school_gate_finale":
        if "express_romance" in actions:
            ev["player_stance"] = "romance"
        elif actions & {"reject_romance", "choose_friends"}:
            ev["player_stance"] = "friends"
        elif "leave" in topics:
            ev["player_stance"] = "leave"
        if topics & {"romance", "misunderstanding", "class_change", "distance"}:
            ev["relationship_talk"] = True

    return ev


def _turns(state: dict[str, Any]) -> int:
    return int(state.get("storylet_turns", 0))


def evaluate(
    state: dict[str, Any],
    storylet: Storylet,
    analysis: Analysis,
) -> Progress:
    """根据累积证据判定结果；返回 outcome=None 表示继续等待。"""
    ev = state.get("storylet_evidence", {})
    sid = storylet.id
    turns = _turns(state)
    rel = state["relationship"]

    if sid == "old_note":
        if ev.get("cold"):
            return Progress("distance_kept", "玩家在旧事上仍然只顾催她")
        if ev.get("engaged"):
            return Progress("nostalgia_shared", "玩家接住了旧便签这条线")
        if turns >= 1:
            return Progress("topic_avoided", "玩家没有接旧便签的话题")
        return Progress(None, "等待玩家回应便签")

    if sid == "direct_question":
        if ev.get("distance_talk"):
            return Progress("admitted_distance", "玩家在问疏远/在意的事")
        if ev.get("partial_talk"):
            return Progress("partial_truth", "玩家把话题引到分班/陈屿")
        if turns >= 1:
            return Progress("deflected", "玩家没有接这个问题")
        return Progress(None, "等她先开口")

    if sid == "chenyu_hint":
        if ev.get("chenyu_talk"):
            return Progress("hint_received", "玩家追问了陈屿")
        if ev.get("distance_talk"):
            return Progress("topic_dropped", "玩家没有接陈屿这条线")
        if turns >= 1:
            return Progress("suspicion_raised", "玩家没有回应")
        return Progress(None, "等待回应")

    if sid == "late_explanation":
        if ev.get("pressure"):
            return Progress("worse", "玩家在解释时又替她做决定")
        strong = (
            ev.get("explanation_offered")
            and ev.get("quote_discussed")
            and rel["trust"] >= 42
            and rel["respect_for_autonomy"] >= 40
        )
        if strong:
            return Progress("clarified", "玩家说明了原话的含义，且之前的交流建立了足够信任")
        if ev.get("explanation_offered") and ev.get("quote_discussed"):
            return Progress("partially_clarified", "解释了，但她还没完全放下")
        if ev.get("quote_discussed") and turns >= 1:
            return Progress("partially_clarified", "只把话说开了一半")
        if turns >= 2:
            return Progress("partially_clarified", "没有更多证据，停在半开状态")
        return Progress(None, "等她/玩家继续说")

    if sid == "class_choice":
        if ev.get("pressure"):
            return Progress("conflict_emerged", "玩家试图替她决定分班")
        if ev.get("future_talk") and (ev.get("class_plan") or ev.get("respectful")):
            return Progress("discussed_respectfully", "谈到了分班计划和之后的相处")
        if ev.get("class_plan") or ev.get("respectful"):
            return Progress(None, "只谈到分班本身，还没谈之后的相处")
        if turns >= 2:
            return Progress("topic_avoided", "只提了分班，没有真正讨论计划与未来")
        return Progress(None, "等她继续")

    if sid == "walk_home":
        if ev.get("player_accepted"):
            return Progress("walked_together", "玩家明确接受同行")
        if ev.get("player_declined"):
            return Progress("walked_apart", "玩家拒绝或先走了")
        if turns >= 1:
            return Progress("walked_apart", "玩家没有回应邀请，各自离开")
        return Progress(None, "等她/玩家表态")

    if sid == "shared_memory":
        if ev.get("different"):
            return Progress("different_understanding", "同一段记忆，两个人的理解不同")
        if ev.get("engaged"):
            return Progress("shared_warmth", "玩家接住了共同的记忆")
        if turns >= 1:
            return Progress("memory_avoided", "玩家没有接这段回忆")
        return Progress(None, "等待回应")

    if sid == "unfinished_conversation":
        if ev.get("pressure"):
            return Progress("worsened", "玩家再次越界，冲突加深")
        if (ev.get("explanation") or ev.get("apology")) and ev.get("feelings"):
            return Progress("repaired", "双方把没说完的话说开了一些")
        if ev.get("feelings"):
            return Progress("partially_understood", "表达了感受，但还没真正和解")
        if turns >= 2:
            return Progress("avoided", "两个人都没有再往下说")
        return Progress(None, "等待回应")

    if sid == "school_gate_finale":
        if ev.get("player_stance") or (ev.get("relationship_talk") and turns >= 1):
            return Progress("finale_ready", "双方已经表态或有明确的关系话题")
        if turns >= 1:
            return Progress("finale_ready", "该说的已经说得差不多了")
        return Progress(None, "还差最后一句")

    # 未登记的事件：不自动完成
    return Progress(None, "未登记的事件类型，等待更多证据")


def should_abandon(state: dict[str, Any], storylet: Storylet) -> tuple[bool, str]:
    """事件是否应当放弃（无结果、不写事实）。"""
    if state.get("scene") not in storylet.allowed_scenes:
        return True, "场景已经变化"
    if _turns(state) >= MAX_TURNS.get(storylet.id, 3):
        return True, "超过最大互动轮数仍未产生结果"
    return False, ""
