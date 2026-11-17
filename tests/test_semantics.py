"""P0-1 语义正确性回归：否定、引用、疑问、假设不能反向改写事实。"""

from __future__ import annotations

import pytest

from app.rules.meaningful_turn import analyze


def _fact(state: dict, name: str) -> bool:
    return bool(state["facts"][name])


# ---------------- 文本理解层 ----------------

@pytest.mark.parametrize("text", [
    "我不喜欢你",
    "我没有说我喜欢你",
    "你是不是觉得我喜欢你？",
    "陈屿说「我喜欢你」",
])
def test_romance_not_confirmed(text):
    analysis = analyze(text)
    assert "express_romance" not in analysis.actions, text


def test_negative_romance_is_a_real_signal():
    analysis = analyze("我不喜欢你")
    assert "reject_romance" in analysis.actions
    assert "express_romance" not in analysis.actions


def test_quoted_speech_is_ignored():
    analysis = analyze("陈屿说「我喜欢你」")
    assert analysis.quoted
    assert "express_romance" not in analysis.actions


def test_hypothetical_not_committed():
    analysis = analyze("如果我说我喜欢你，你会怎么办？")
    assert "express_romance" not in analysis.actions


def test_wish_is_not_control():
    analysis = analyze("我希望你不要为了我放弃重点班")
    assert "control_autonomy" not in analysis.actions
    assert "support_autonomy" in analysis.actions


def test_direct_pressure_is_control():
    analysis = analyze("你必须放弃重点班陪我")
    assert "control_autonomy" in analysis.actions


def test_complex_support_keeps_both_feelings():
    analysis = analyze("我支持你去重点班，但我确实会舍不得")
    assert "support_autonomy" in analysis.actions
    assert "control_autonomy" not in analysis.actions


def test_question_about_class_does_not_decide_anything():
    analysis = analyze("作业写完了吗？")
    assert "class_change" not in analysis.topics
    assert "romance" not in analysis.topics
    assert analysis.actions == [] or set(analysis.actions) <= {"small_talk"}


# ---------------- 完整 /interact 状态提交层 ----------------

def test_negative_confession_does_not_set_romance(engine):
    start = engine.start()
    gid = start["game_id"]
    engine.interact(gid, "我不喜欢你。", "req_sem_0000001")
    state = engine.get_state(gid, include_internal=True)["state"]
    assert _fact(state, "player_expressed_romance") is False
    assert _fact(state, "player_declined_romance") is True


def test_reported_confession_does_not_set_romance(engine):
    start = engine.start()
    gid = start["game_id"]
    engine.interact(gid, "陈屿说「我喜欢你」。", "req_sem_0000002")
    state = engine.get_state(gid, include_internal=True)["state"]
    assert _fact(state, "player_expressed_romance") is False


def test_question_confession_does_not_set_romance(engine):
    start = engine.start()
    gid = start["game_id"]
    engine.interact(gid, "你是不是觉得我喜欢你？", "req_sem_0000003")
    state = engine.get_state(gid, include_internal=True)["state"]
    assert _fact(state, "player_expressed_romance") is False


def test_wish_not_control_but_support(engine):
    start = engine.start()
    gid = start["game_id"]
    engine.interact(gid, "我希望你不要为了我放弃重点班。", "req_sem_0000004")
    state = engine.get_state(gid, include_internal=True)["state"]
    assert _fact(state, "player_controlling") is False
    assert state["relationship"]["respect_for_autonomy"] >= 50


def test_pressure_sets_control(engine):
    start = engine.start()
    gid = start["game_id"]
    engine.interact(gid, "你必须放弃重点班陪我。", "req_sem_0000005")
    state = engine.get_state(gid, include_internal=True)["state"]
    assert _fact(state, "player_controlling") is True
    assert state["relationship"]["respect_for_autonomy"] < 50


def test_support_without_class_topic_does_not_claim_discussion(engine):
    start = engine.start()
    gid = start["game_id"]
    engine.interact(gid, "我支持你。", "req_sem_0000006")
    state = engine.get_state(gid, include_internal=True)["state"]
    assert _fact(state, "class_change_discussed") is False


def test_support_with_class_topic_does_not_claim_discussion(engine):
    """表态支持 ≠ 已经认真谈过分班计划与未来（后者只由事件结算写入）。"""
    start = engine.start()
    gid = start["game_id"]
    engine.interact(gid, "我支持你去重点班，但我确实会舍不得。", "req_sem_0000007")
    state = engine.get_state(gid, include_internal=True)["state"]
    assert _fact(state, "class_change_discussed") is False
    assert _fact(state, "player_controlling") is False
    assert state["relationship"]["respect_for_autonomy"] >= 52


def test_smalltalk_does_not_touch_main_facts(engine):
    start = engine.start()
    gid = start["game_id"]
    engine.interact(gid, "作业写完了吗？", "req_sem_0000008")
    state = engine.get_state(gid, include_internal=True)["state"]
    assert _fact(state, "class_change_discussed") is False
    assert _fact(state, "misunderstanding_discussed") is False
    assert _fact(state, "player_expressed_romance") is False
