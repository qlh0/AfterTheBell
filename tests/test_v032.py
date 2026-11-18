"""v0.3.2：解释识别、同行邀请留一轮、分班安慰给尊重分。"""

from __future__ import annotations

import pytest

from app import game_state as gs
from app.content import load_content
from app.rules import actions
from app.rules.meaningful_turn import analyze
from app.rules.storylet_progress import initial_evidence


@pytest.fixture(scope="module")
def content():
    return load_content()


def _force_active(engine, game_id: str, storylet_id: str, scene: str | None = None,
                  facts: dict | None = None, trust: int | None = None):
    state = engine.db.load_state(game_id)
    storylet = engine.content.storylets.get(storylet_id)
    if scene:
        state["scene"] = scene
    state["active_storylet"] = storylet_id
    state["storylet_stage"] = "active"
    state["storylet_evidence"] = initial_evidence(storylet, state)
    state["storylet_turns"] = 0
    state["storylet_started_turn"] = state["turn_index"]
    state["scheduled_storylet"] = None
    if storylet_id not in state["used_storylets"]:
        state["used_storylets"].append(storylet_id)
    if facts:
        state["facts"].update(facts)
    if trust is not None:
        state["relationship"]["trust"] = trust
    state["state_version"] += 1
    engine.db.save_state(state)


def test_clear_explanation_is_parsed_as_explain():
    a = analyze("我说的不是你，那天是在说陈屿他们班。")
    assert "explain_own_words" in a.actions
    assert "ask_chenyu" in a.actions


def test_explanation_action_sets_player_explained_quote(content):
    state = gs.default_state("g_v032", content.goal_ids(), content.budget())
    analysis = analyze("我说的不是你，那天是在说陈屿他们班。")
    actions.commit_actions(state, analysis.actions, "test", analysis=analysis)
    assert state["facts"]["player_explained_quote"] is True
    assert state["facts"]["misunderstanding_discussed"] is True


def test_late_explanation_uses_their_phrasing(engine):
    start = engine.start()
    gid = start["game_id"]
    _force_active(engine, gid, "late_explanation", trust=50,
                  facts={"misunderstanding_discussed": True})
    engine.interact(gid, "我说的不是你，那天是在说陈屿他们班。", "req_v032_000001")
    state = engine.get_state(gid, include_internal=True)["state"]
    assert state["facts"]["misunderstanding_resolved"] is True
    resolved = [e for e in engine.get_events(gid)["events"]
                if e["event_id"] == "late_explanation" and e["status"] == "resolved"]
    assert resolved and resolved[0]["payload"]["outcome"] == "clarified"


def test_walk_home_gives_player_one_turn_to_accept(engine):
    start = engine.start()
    gid = start["game_id"]
    _force_active(engine, gid, "walk_home", scene="school_gate", trust=50)

    engine.interact(gid, "今天天气不错。", "req_v032_000002")
    state = engine.get_state(gid, include_internal=True)["state"]
    assert state["active_storylet"] == "walk_home", "邀请当轮不应直接判各自离开"
    assert state["facts"]["walk_home_done"] is False

    engine.interact(gid, "好，一起走吧。", "req_v032_000003")
    state = engine.get_state(gid, include_internal=True)["state"]
    assert state["facts"]["walk_home_done"] is True
    resolved = [e for e in engine.get_events(gid)["events"]
                if e["event_id"] == "walk_home" and e["status"] == "resolved"]
    assert resolved[0]["payload"]["outcome"] in {"walked_together", "walked_and_talked"}


def test_walk_home_ignored_next_turn_resolves_apart(engine):
    start = engine.start()
    gid = start["game_id"]
    _force_active(engine, gid, "walk_home", scene="school_gate", trust=50)

    engine.interact(gid, "嗯。", "req_v032_000004")
    engine.interact(gid, "嗯。", "req_v032_000005")
    state = engine.get_state(gid, include_internal=True)["state"]
    assert state["facts"]["walk_home_done"] is False
    resolved = [e for e in engine.get_events(gid)["events"]
                if e["event_id"] == "walk_home" and e["status"] == "resolved"]
    assert resolved and resolved[0]["payload"]["outcome"] == "walked_apart"


def test_class_reassurance_adds_respect(engine):
    start = engine.start()
    gid = start["game_id"]
    engine.interact(gid, "能和你在一个班最好，不过就算不在一个班我们也在一个学校。",
                    "req_v032_000006")
    state = engine.get_state(gid, include_internal=True)["state"]
    assert state["relationship"]["respect_for_autonomy"] == 52

    engine.interact(gid, "没事，还是能见的，而且放学我们也可以一起走呀。",
                    "req_v032_000007")
    state = engine.get_state(gid, include_internal=True)["state"]
    assert state["relationship"]["respect_for_autonomy"] == 54

    engine.interact(gid, "我说的不是你，那天是在说陈屿他们班。", "req_v032_000008")
    state = engine.get_state(gid, include_internal=True)["state"]
    assert state["relationship"]["respect_for_autonomy"] >= 55
