"""事件收尾：由「玩家实际说了什么」+「她对玩家动作的反应」决定事件结果。

故事事件不是脚本，而是情境。结果必须来自本回合真实发生的互动：
- 玩家解释了 → 才可能澄清；
- 玩家替她决定 → 一定产生尊重冲突；
- 玩家避而不谈 → 就只能是 topic_avoided。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .. import game_state as gs
from ..rules.meaningful_turn import Analysis
from ..narrative.storylets import Storylet


@dataclass
class Resolution:
    outcome: str
    changes: list[dict[str, Any]] = field(default_factory=list)
    narration: list[str] = field(default_factory=list)
    memory: tuple[str, str, int, list[str]] | None = None  # (kind, content, importance, tags)


def _apply(
    state: dict[str, Any], rel: dict[str, int], facts: list[str], reason: str
) -> list[dict[str, Any]]:
    changes = gs.apply_relationship_delta(state, rel, reason)
    changes += gs.apply_fact_changes(state, facts, reason)
    return changes


def _resolve_old_note(state: dict[str, Any], analysis: Analysis) -> Resolution:
    if analysis.controlling:
        changes = _apply(state, {"respect_for_autonomy": -1}, [], "old_note")
        return Resolution(
            outcome="distance_kept",
            changes=changes,
            narration=["她把便签收了回去，动作比刚才快。", "那段以前好像突然变得不合时宜。"],
            memory=("episode", "旧便签：玩家当时只顾着催她，气氛变冷了。", 2, ["old_note"]),
        )
    if analysis.topics & {"distance", "romance", "care", "misunderstanding"}:
        changes = _apply(state, {"trust": 2, "affection": 2}, [], "old_note")
        return Resolution(
            outcome="nostalgia_shared",
            changes=changes,
            narration=["她盯着便签上的字看了一会儿，没忍住笑了一下，又很快压回去。"],
            memory=("episode", "旧便签：两人一起想起以前传纸条的日子。", 4, ["old_note", "history"]),
        )
    changes = _apply(state, {"affection": 1}, [], "old_note")
    return Resolution(
        outcome="topic_avoided",
        changes=changes,
        narration=["她把便签塞回书里，换了个话题。"],
        memory=("episode", "旧便签：玩家没有接住她递出来的旧事。", 2, ["old_note"]),
    )


def _resolve_direct_question(state: dict[str, Any], analysis: Analysis) -> Resolution:
    if analysis.topics & {"distance", "misunderstanding", "care"}:
        changes = _apply(
            state, {"trust": 3, "affection": 1}, ["distance_noticed"], "direct_question"
        )
        return Resolution(
            outcome="admitted_distance",
            changes=changes,
            narration=["她先低头把笔帽按了回去，才慢慢开口。"],
            memory=("episode", "玩家直接问她最近为什么冷淡，她承认了一点。", 5, ["distance"]),
        )
    if analysis.topics & {"class_change", "chenyu"}:
        changes = _apply(state, {"trust": 1}, [], "direct_question")
        return Resolution(
            outcome="partial_truth",
            changes=changes,
            narration=["她话到一半停住，像在衡量要不要说下去。"],
            memory=("episode", "她差点说出疏远的原因，又自己收住了。", 3, ["distance", "secret"]),
        )
    changes = _apply(state, {"trust": -1}, [], "direct_question")
    return Resolution(
        outcome="deflected",
        changes=changes,
        narration=["她把话推了回来，语气有点用力。"],
        memory=None,
    )


def _resolve_chenyu_hint(state: dict[str, Any], analysis: Analysis) -> Resolution:
    if analysis.topics & {"chenyu", "misunderstanding"}:
        changes = _apply(state, {"trust": 2}, ["chenyu_hint_seen"], "chenyu_hint")
        return Resolution(
            outcome="hint_received",
            changes=changes,
            narration=["她停了停，像在斟酌该说多少。"],
            memory=("episode", "陈屿这条线提供了一点线索，但许栀显然不想多说。", 4, ["chenyu"]),
        )
    changes = _apply(state, {"trust": -1}, [], "chenyu_hint")
    return Resolution(
        outcome="suspicion_raised",
        changes=changes,
        narration=["她说完自己先皱了下眉，好像也觉得没必要。"],
        memory=("episode", "提到陈屿时她有点在意，但没解释。", 3, ["chenyu", "jealousy"]),
    )


def _resolve_late_explanation(state: dict[str, Any], analysis: Analysis) -> Resolution:
    rel = state["relationship"]
    if analysis.controlling:
        changes = _apply(
            state, {"respect_for_autonomy": -5, "trust": -3}, [], "late_explanation"
        )
        return Resolution(
            outcome="worse",
            changes=changes,
            narration=["她把脸别过去，肩膀绷了一下。"],
            memory=("episode", "解释那句话的时候，玩家又替她做了决定，谈得更僵了。", 5, ["misunderstanding"]),
        )
    if "explain_own_words" in analysis.actions:
        if rel["trust"] >= 42 and rel["respect_for_autonomy"] >= 40:
            changes = _apply(
                state,
                {"trust": 6, "affection": 4},
                ["misunderstanding_resolved", "misunderstanding_discussed"],
                "late_explanation",
            )
            return Resolution(
                outcome="clarified",
                changes=changes,
                narration=["她听完，很久没说话。", "然后她把放在桌沿的手收了回去。"],
                memory=("promise", "误会解开了：那句话是在说别人，不是嫌弃她。", 5, ["misunderstanding"]),
            )
        changes = _apply(
            state, {"trust": 2, "affection": 1}, ["misunderstanding_discussed"], "late_explanation"
        )
        return Resolution(
            outcome="partially_clarified",
            changes=changes,
            narration=["她听你把话说完，点了点头，又不知道该怎么接。"],
            memory=("episode", "玩家解释了那句话，但她还留着一半怀疑。", 4, ["misunderstanding"]),
        )
    changes = _apply(state, {"trust": 1}, ["misunderstanding_discussed"], "late_explanation")
    return Resolution(
        outcome="partially_clarified",
        changes=changes,
        narration=["她听你把话说完，没有立刻回应。"],
        memory=("episode", "那句话被提起来了，但没有真正说开。", 3, ["misunderstanding"]),
    )


def _resolve_class_choice(state: dict[str, Any], analysis: Analysis) -> Resolution:
    if analysis.controlling or "control_autonomy" in analysis.actions:
        changes = _apply(
            state,
            {"respect_for_autonomy": -6, "trust": -2},
            ["class_change_discussed", "player_controlling"],
            "class_choice",
        )
        return Resolution(
            outcome="conflict_emerged",
            changes=changes,
            narration=["她把那张纸收进抽屉，动作重了一点。"],
            memory=("conflict", "玩家想替她决定要不要报重点班，她明确反感。", 5, ["class_change", "autonomy"]),
        )
    if analysis.topics & {"class_change", "care", "romance"} or "support_autonomy" in analysis.actions:
        changes = _apply(
            state, {"respect_for_autonomy": 4, "trust": 2}, ["class_change_discussed"], "class_choice"
        )
        return Resolution(
            outcome="discussed_respectfully",
            changes=changes,
            narration=["她说得很慢，一边说一边看你的反应。"],
            memory=("episode", "两人认真谈过分班：她想去理重点班，玩家没有替她做决定。", 5, ["class_change", "respect"]),
        )
    changes = _apply(state, {"respect_for_autonomy": 1}, [], "class_choice")
    return Resolution(
        outcome="topic_avoided",
        changes=changes,
        narration=["她把纸往书里一夹，把话题放下了。"],
        memory=("episode", "分班的话题被她推到了以后。", 2, ["class_change"]),
    )


def _resolve_walk_home(state: dict[str, Any], analysis: Analysis) -> Resolution:
    if "leave" in analysis.topics and "romance" not in analysis.topics:
        changes = _apply(state, {"affection": -1}, ["walk_home_done"], "walk_home")
        return Resolution(
            outcome="walked_apart",
            changes=changes,
            narration=["她站在路灯下没动，等你走出几步才转身。"],
            memory=("episode", "放学时玩家先走了，没有一起走。", 3, ["walk_home"]),
        )
    changes = _apply(
        state, {"trust": 3, "affection": 3}, ["walk_home_done"], "walk_home"
    )
    return Resolution(
        outcome="walked_together",
        changes=changes,
        narration=["你们并肩走了一段，谁都没先提分班的事。", "路灯一盏一盏亮起来，她的步子比平时慢。"],
        memory=("episode", "两人一起走了一段放学路，气氛缓和。", 4, ["walk_home"]),
    )


_RESOLVERS = {
    "old_note": _resolve_old_note,
    "direct_question": _resolve_direct_question,
    "chenyu_hint": _resolve_chenyu_hint,
    "late_explanation": _resolve_late_explanation,
    "class_choice": _resolve_class_choice,
    "walk_home": _resolve_walk_home,
}


def resolve(
    state: dict[str, Any],
    storylet: Storylet,
    analysis: Analysis,
    proposed_outcome: str | None = None,
) -> Resolution | None:
    """finale 由结局引擎处理，这里返回 None 表示跳过。"""
    if storylet.kind == "finale":
        return None
    resolver = _RESOLVERS.get(storylet.id)
    if resolver is None:
        return Resolution(outcome=storylet.possible_outcomes[0] if storylet.possible_outcomes else "resolved")
    res = resolver(state, analysis)
    # 结果必须在内容声明过的 possible_outcomes 里
    if res.outcome not in storylet.possible_outcomes:
        res.outcome = storylet.possible_outcomes[0]
    return res
