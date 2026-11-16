"""规则层单测：前置条件 DSL、回合判定、数值上下限、结局资格。"""

from __future__ import annotations

import pytest

from app import game_state as gs
from app.rules import actions, endings, meaningful_turn, preconditions
from app.content import load_content


@pytest.fixture(scope="module")
def content():
    return load_content()


# ---------------- 前置条件 ----------------

def test_predicate_operators():
    state = {
        "scene": "classroom",
        "meaningful_turns": 4,
        "ending_phase": "none",
        "active_storylet": None,
        "relationship": {"trust": 52},
        "facts": {"foo": True},
        "narrative_goals": {"g": "pending"},
    }
    assert preconditions.evaluate({"eq": ["scene", "classroom"]}, state)
    assert preconditions.evaluate({"gte": ["relationship.trust", 50]}, state)
    assert preconditions.evaluate({"lt": ["relationship.trust", 60]}, state)
    assert preconditions.evaluate({"in": ["ending_phase", ["none", "eligible"]]}, state)
    assert preconditions.evaluate({"flag": ["facts.foo", True]}, state)
    assert preconditions.evaluate({"falsy": ["active_storylet"]}, state)
    assert preconditions.evaluate({"falsy": ["active_storylet"]}, state)
    assert preconditions.evaluate({"all": [
        {"eq": ["scene", "classroom"]},
        {"any": [{"gte": ["meaningful_turns", 9]}, {"lt": ["meaningful_turns", 5]}]},
    ]}, state)
    assert not preconditions.evaluate({"not": {"eq": ["scene", "classroom"]}}, state)
    # 未知路径一律 False，不抛异常
    assert not preconditions.evaluate({"eq": ["nope.nope", 1]}, state)


def test_bool_is_not_int():
    state = {"facts": {"x": True}, "relationship": {}}
    assert not preconditions.evaluate({"eq": ["facts.x", 1]}, state)
    assert preconditions.evaluate({"eq": ["facts.x", True]}, state)


def test_invalid_predicate_is_rejected():
    with pytest.raises(preconditions.PredicateError):
        preconditions.validate({"unknown_op": 1}, where="test")


def test_storylet_content_is_valid(content):
    # 内容加载时已经过 validate；这里再确认事件数与目标数
    assert len(content.storylets) == 7
    ids = {s.id for s in content.storylets.all()}
    assert {"old_note", "direct_question", "chenyu_hint", "late_explanation",
            "class_choice", "walk_home", "school_gate_finale"} <= ids
    assert set(content.goals) == {"notice_distance", "clarify_misunderstanding",
                                  "discuss_class_change", "define_relationship"}


# ---------------- 回合判定 ----------------

@pytest.mark.parametrize("text,expected", [
    ("你最近是不是在躲我？", True),
    ("我喜欢你。", True),
    ("你不许去重点班。", True),
    ("嗯。", False),
    ("哈哈。", False),
    ("今天好热。", False),
])
def test_meaningful_turn(text, expected):
    assert meaningful_turn.analyze(text).is_meaningful is expected


def test_controlling_detected():
    analysis = meaningful_turn.analyze("你不许去重点班，听我的。")
    assert analysis.controlling
    assert "control_autonomy" in analysis.actions


# ---------------- 数值与动作 ----------------

def test_relationship_clamped():
    state = {"relationship": {"affection": 98, "trust": 2, "respect_for_autonomy": 50}, "facts": {}}
    changes = gs.apply_relationship_delta(state, {"affection": 10, "trust": -10}, "test")
    assert state["relationship"]["affection"] == 100
    assert state["relationship"]["trust"] == 0
    assert {c["path"] for c in changes} == {"relationship.affection", "relationship.trust"}


def test_unknown_action_is_dropped():
    state = {"relationship": {"affection": 50, "trust": 50, "respect_for_autonomy": 50}, "facts": {}}
    changes, notes = actions.commit_actions(state, ["summon_dragon"])
    assert changes == []
    assert any("ignored_unknown_action" in n for n in notes)


def test_duplicate_action_applied_once():
    state = {"relationship": {"affection": 50, "trust": 50, "respect_for_autonomy": 50}, "facts": {}}
    actions.commit_actions(state, ["support_autonomy"] * 6)
    assert state["relationship"]["respect_for_autonomy"] == 54


def test_per_turn_cap():
    state = {"relationship": {"affection": 50, "trust": 50, "respect_for_autonomy": 50}, "facts": {}}
    # 四个不同动作都加信任：3+4+2+2 = 11，应被截断到上限 9
    actions.commit_actions(state, ["clarify_quote", "explain_own_words", "ask_distance", "care"])
    assert state["relationship"]["trust"] == 50 + actions.PER_TURN_CAP


# ---------------- 结局 ----------------

def _base_state(content):
    return gs.default_state("g", content.goal_ids(), content.budget())


def test_affection_alone_never_gives_romance(content):
    state = _base_state(content)
    state["relationship"] = {"affection": 100, "trust": 100, "respect_for_autonomy": 100}
    state["facts"]["misunderstanding_resolved"] = True
    state["facts"]["finale_resolved"] = True
    state["narrative_goals"]["define_relationship"] = "done"
    # 没有 class_change_discussed、没有 player_expressed_romance、mutual_intent 仍是 unknown
    assert endings.pick_ending(state, content) != "romance"


def test_romance_requires_both_sides(content):
    state = _base_state(content)
    state["relationship"] = {"affection": 80, "trust": 70, "respect_for_autonomy": 70}
    state["facts"].update({
        "misunderstanding_resolved": True,
        "class_change_discussed": True,
        "player_expressed_romance": True,
        "finale_resolved": True,
    })
    state["narrative_goals"]["define_relationship"] = "done"
    state["npc"]["mutual_intent"] = "romance"
    assert endings.pick_ending(state, content) == "romance"


def test_no_ending_gate_passes_without_finale(content):
    state = _base_state(content)
    assert endings.pick_ending(state, content) == "missed"
    assert not endings.finale_eligible(state)


def test_finale_only_at_school_gate(content):
    state = _base_state(content)
    state["meaningful_turns"] = 12
    assert not endings.finale_eligible(state)
    state["scene"] = "school_gate"
    assert endings.finale_eligible(state)
