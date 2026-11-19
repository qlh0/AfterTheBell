"""调度器：安排事件（scheduled）→ 到点激活（active）→ 复核是否仍然合法。

规则：
- 只在「导演挑中 + 前置条件仍成立 + 状态版本未变」时安排；
- 激活前再复核一次，过时就丢弃并记录原因；
- 结局 finale 不走排队，条件满足直接激活（避免玩家卡在收束）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .. import game_state as gs
from ..rules import endings as endings_rules
from ..rules import preconditions
from ..rules.storylet_progress import initial_evidence
from . import director
from .storylets import Storylet, StoryletLibrary


@dataclass
class Activation:
    storylet: Storylet
    cue: str
    how: str  # "scheduled" | "finale"
    exposition: tuple[str, ...] = ()


@dataclass
class PlanResult:
    status: str  # scheduled | skipped | not_required
    storylet_id: str | None
    reason: str
    director: Any = None  # DirectorChoice（记录导演决策与指标，便于调试）


def _mark_used(state: dict[str, Any], storylet_id: str) -> None:
    used = state.setdefault("used_storylets", [])
    if storylet_id not in used:
        used.append(storylet_id)


def _choose_variant(state: dict[str, Any], storylet: Storylet) -> dict[str, Any] | None:
    """按当前事实选择场景变体（例如共同回忆要指名是哪一段回忆）。"""
    for variant in storylet.variants:
        when = variant.get("when")
        if when and preconditions.evaluate(when, state):
            return variant
    return None


def _activate(state: dict[str, Any], storylet: Storylet, how: str) -> Activation:
    state["active_storylet"] = storylet.id
    state["storylet_started_turn"] = state["turn_index"]
    state["storylet_stage"] = "active"
    state["storylet_evidence"] = initial_evidence(storylet, state)
    state["storylet_turns"] = 0
    state["scheduled_storylet"] = None
    state["scheduled_at_version"] = None
    _mark_used(state, storylet.id)

    if storylet.enter_scene:
        # 插曲事件：进入图书馆/走廊/小卖部，结束后回到 return_scene
        state["return_scene"] = storylet.return_scene or state["scene"]
        state["scene"] = storylet.enter_scene

    variant = _choose_variant(state, storylet)
    cue = (variant or {}).get("cue") or storylet.opening_cue
    exposition = tuple((variant or {}).get("exposition") or storylet.exposition)

    if storylet.id == "old_note":
        state["facts"]["old_note_seen"] = True
    if storylet.id == "chenyu_hint":
        state["facts"]["chenyu_hint_seen"] = True
    if storylet.kind == "finale":
        endings_rules.prepare(state)
    return Activation(
        storylet=storylet,
        cue=cue,
        how=how,
        exposition=exposition,
    )


def try_activate(state: dict[str, Any], library: StoryletLibrary) -> Activation | None:
    """在新一回合开始 / advance 时调用。"""
    if state["active_storylet"] or state["ending_phase"] == "committed":
        return None

    # 先让结局状态机给出资格，finale 的候选条件才可能成立
    endings_rules.maybe_make_eligible(state)

    scheduled_id = state.get("scheduled_storylet")
    if scheduled_id:
        storylet = library.get(scheduled_id)
        if storylet is None:
            state["scheduled_storylet"] = None
            return None
        if library.is_still_eligible(scheduled_id, state):
            return _activate(state, storylet, "scheduled")
        state["scheduled_storylet"] = None
        state["scheduled_at_version"] = None
        state.setdefault("dropped_storylets", []).append(
            {"id": scheduled_id, "reason": "preconditions_changed", "at_version": state["state_version"]}
        )
        # 过时就不再强推，退回让导演重新规划

    # 收束阶段：finale 直接激活，不进队列
    finale = library.get("school_gate_finale")
    if (
        finale is not None
        and "school_gate_finale" not in set(state.get("used_storylets") or [])
        and endings_rules.finale_eligible(state)
        and library.is_still_eligible("school_gate_finale", state)
    ):
        return _activate(state, finale, "finale")

    return None


def trigger_by_text(
    state: dict[str, Any], library: StoryletLibrary, text: str
) -> Activation | None:
    """玩家这句话里出现「去图书馆/走廊/小卖部」等关键词时，直接进入插曲。"""
    if state.get("active_storylet") or state.get("ending_phase") == "committed":
        return None
    lowered = text or ""
    for storylet in library.manual_eligible(state):
        if not storylet.trigger_keywords:
            continue
        if any(keyword in lowered for keyword in storylet.trigger_keywords):
            return _activate(state, storylet, "keyword")
    return None


def force_finale(state: dict[str, Any], library: StoryletLibrary) -> Activation | None:
    """到硬上限前强制进入校门口收束，保证结局前还有一段有效对话。"""
    if state.get("ending_phase") == "committed":
        return None
    finale = library.get("school_gate_finale")
    if finale is None:
        return None
    state["day"] = 2
    state["scene"] = "school_gate"
    if state.get("active_storylet") not in (None, finale.id):
        clear_active(state)
    if state.get("active_storylet") == finale.id:
        return None
    endings_rules.prepare(state)
    return _activate(state, finale, "forced")


def plan_next(
    state: dict[str, Any],
    library: StoryletLibrary,
    reason: str,
    chooser: Any = None,
) -> PlanResult:
    """决定下一个事件。

    `chooser(state, eligible)` 可选：M2 传入 LLM 导演；返回 None 表示"导演没给出
    决定"，则退回确定性打分。返回 DirectorChoice 时，no_event 也是合法决定。
    """
    ok, why = director.should_plan(state, reason)
    if not ok:
        return PlanResult(status="not_required", storylet_id=None, reason=why)

    eligible = library.eligible(state)
    if not eligible:
        return PlanResult(status="skipped", storylet_id=None, reason="没有满足条件的候选事件")

    snapshot_version = state["state_version"]
    choice = None
    chosen_id: str | None = None

    if chooser is not None:
        choice = chooser(state, eligible)
        if choice is not None:
            chosen_id = choice.storylet_id
    if choice is None:
        chosen = director.propose(state, eligible)
        chosen_id = chosen.id if chosen else None

    # 无论选没选，都记下这次规划回合，避免连续追问导演
    state["last_plan_turn"] = state["turn_index"]

    if chosen_id is None:
        return PlanResult(status="skipped", storylet_id=None, reason="导演选择 no_event", director=choice)

    # 提交前复核：候选仍合法、且基于同一状态版本
    if not library.is_still_eligible(chosen_id, state) or snapshot_version != state["state_version"]:
        return PlanResult(status="skipped", storylet_id=None, reason="候选在提交前失效", director=choice)

    state["scheduled_storylet"] = chosen_id
    state["scheduled_at_version"] = snapshot_version
    return PlanResult(status="scheduled", storylet_id=chosen_id, reason=why, director=choice)


def clear_active(state: dict[str, Any]) -> None:
    state["active_storylet"] = None
    state["storylet_started_turn"] = None
    state["storylet_stage"] = "none"
    state["storylet_turns"] = 0
