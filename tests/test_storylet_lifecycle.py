"""P0-2：事件必须有互动证据才结算，不能一句话自动完成。"""

from __future__ import annotations

import pytest

from app import game_state as gs
from app.narrative import scheduler
from app.rules.storylet_progress import initial_evidence


def _force_active(engine, game_id: str, storylet_id: str, scene: str | None = None,
                  facts: dict | None = None, trust: int | None = None):
    state = engine.db.load_state(game_id)
    storylet = engine.content.storylets.get(storylet_id)
    if scene:
        state["scene"] = scene
    state["active_storylet"] = storylet_id
    state["storylet_stage"] = "active"
    state["storylet_evidence"] = initial_evidence(storylet)
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
    return state


def _events(engine, game_id, status=None):
    items = engine.get_events(game_id)["events"]
    return [e for e in items if status is None or e["status"] == status]


def test_walk_home_not_completed_by_unrelated_line(engine):
    start = engine.start()
    gid = start["game_id"]
    _force_active(engine, gid, "walk_home", scene="school_gate", trust=50)

    engine.interact(gid, "作业写完了吗？", "req_life_0000001")
    state = engine.get_state(gid, include_internal=True)["state"]
    assert state["facts"]["walk_home_done"] is False
    resolved = [e for e in _events(engine, gid, "resolved") if e["event_id"] == "walk_home"]
    assert resolved and resolved[0]["payload"]["outcome"] != "walked_together"


def test_class_choice_not_completed_by_care(engine):
    start = engine.start()
    gid = start["game_id"]
    _force_active(engine, gid, "class_choice")

    engine.interact(gid, "你累不累？", "req_life_0000002")
    state = engine.get_state(gid, include_internal=True)["state"]
    assert state["facts"]["class_change_discussed"] is False
    resolved = [e for e in _events(engine, gid, "resolved") if e["event_id"] == "class_choice"]
    assert all(e["payload"]["outcome"] != "discussed_respectfully" for e in resolved)


def test_class_choice_requires_plan_and_future(engine):
    start = engine.start()
    gid = start["game_id"]
    _force_active(engine, gid, "class_choice")

    engine.interact(gid, "分班的事，你自己决定就好。", "req_life_0000003")
    state = engine.get_state(gid, include_internal=True)["state"]
    # 只表态支持、没有谈「计划/以后」，不算认真谈过
    assert state["facts"]["class_change_discussed"] is False


def test_class_choice_completes_with_plan_and_future(engine):
    start = engine.start()
    gid = start["game_id"]
    _force_active(engine, gid, "class_choice")

    engine.interact(gid, "你想报重点班就报，那分班以后我们还能一起走吗？", "req_life_0000004")
    state = engine.get_state(gid, include_internal=True)["state"]
    assert state["facts"]["class_change_discussed"] is True


def test_late_explanation_distinct_outcomes(engine):
    # 澄清成功
    start = engine.start()
    gid = start["game_id"]
    _force_active(engine, gid, "late_explanation", trust=50, facts={"misunderstanding_discussed": True})
    engine.interact(gid, "我说的那句话不是在说你，我是说陈屿他们班。", "req_life_0000005")
    state = engine.get_state(gid, include_internal=True)["state"]
    assert state["facts"]["misunderstanding_resolved"] is True

    # 部分澄清
    start2 = engine.start()
    gid2 = start2["game_id"]
    _force_active(engine, gid2, "late_explanation", trust=50, facts={"misunderstanding_discussed": True})
    engine.interact(gid2, "那句话我听见了。", "req_life_0000006")
    state2 = engine.get_state(gid2, include_internal=True)["state"]
    assert state2["facts"]["misunderstanding_resolved"] is False
    assert state2["facts"]["misunderstanding_discussed"] is True

    # 争执升级
    start3 = engine.start()
    gid3 = start3["game_id"]
    _force_active(engine, gid3, "late_explanation", trust=50, facts={"misunderstanding_discussed": True})
    engine.interact(gid3, "你必须听我的，别解释了。", "req_life_0000007")
    state3 = engine.get_state(gid3, include_internal=True)["state"]
    assert state3["facts"]["misunderstanding_resolved"] is False
    assert state3["facts"]["player_controlling"] is True


def test_walk_home_agree_and_refuse_differ(engine):
    start = engine.start()
    gid = start["game_id"]
    _force_active(engine, gid, "walk_home", scene="school_gate", trust=50)
    engine.interact(gid, "一起走吧，正好顺路。", "req_life_0000008")
    assert engine.get_state(gid, True)["state"]["facts"]["walk_home_done"] is True

    start2 = engine.start()
    gid2 = start2["game_id"]
    _force_active(engine, gid2, "walk_home", scene="school_gate", trust=50)
    engine.interact(gid2, "我先走了，明天见。", "req_life_0000009")
    state2 = engine.get_state(gid2, True)["state"]
    assert state2["facts"]["walk_home_done"] is False


def test_event_can_wait_then_resolve_across_turns(engine):
    start = engine.start()
    gid = start["game_id"]
    _force_active(engine, gid, "late_explanation", trust=50, facts={"misunderstanding_discussed": True})

    engine.interact(gid, "你今天怎么样？", "req_life_0000010")
    state = engine.get_state(gid, True)["state"]
    assert state["active_storylet"] == "late_explanation", "证据不足时应继续等待"
    assert state["storylet_stage"] == "interacting"

    engine.interact(gid, "作业写完了吗？", "req_life_0000011")
    state = engine.get_state(gid, True)["state"]
    assert state["active_storylet"] is None
    resolved = [e for e in _events(engine, gid, "resolved") if e["event_id"] == "late_explanation"]
    assert resolved and resolved[0]["payload"]["outcome"] in {"partially_clarified", "worse"}


def test_sudden_leave_does_not_apply_facts(engine):
    start = engine.start()
    gid = start["game_id"]
    _force_active(engine, gid, "old_note")

    engine.interact(gid, "我先走了，明天见。", "req_life_0000012")
    state = engine.get_state(gid, True)["state"]
    assert state["active_storylet"] is None
    assert state["facts"]["class_change_discussed"] is False
    assert state["facts"]["walk_home_done"] is False


def test_resolution_is_applied_once(engine):
    start = engine.start()
    gid = start["game_id"]
    _force_active(engine, gid, "walk_home", scene="school_gate", trust=50)

    engine.interact(gid, "一起走吧。", "req_life_0000013")
    first = engine.get_state(gid, True)["state"]
    trust_after = first["relationship"]["trust"]

    engine.interact(gid, "作业写完了吗？", "req_life_0000014")
    second = engine.get_state(gid, True)["state"]
    resolved = [e for e in _events(engine, gid, "resolved") if e["event_id"] == "walk_home"]
    assert len(resolved) == 1, "事件效果只能应用一次"
    assert second["facts"]["walk_home_done"] is True
    assert second["relationship"]["trust"] >= trust_after - 1


def test_abandoned_event_writes_no_facts(engine):
    start = engine.start()
    gid = start["game_id"]
    _force_active(engine, gid, "chenyu_hint")

    # 第一轮不接话 → 事件等待；第二轮仍不接 → 超过最大轮数，放弃
    engine.interact(gid, "今天好热。", "req_life_0000015")
    state = engine.get_state(gid, True)["state"]
    assert state["active_storylet"] in ("chenyu_hint", None)
    if state["active_storylet"] == "chenyu_hint":
        engine.interact(gid, "今天好热。", "req_life_0000016")
    state = engine.get_state(gid, True)["state"]
    assert state["facts"]["chenyu_hint_seen"] is False
    assert state["active_storylet"] is None
