"""三条玩家路线：主动沟通 → romance，过度干预 → missed，持续回避 → missed。

验收线来自开发说明 §11：同一起点、不同策略，必须产生「实际状态差异」，
而不只是对白不同。
"""

from __future__ import annotations

from app import game_state as gs
from tests.helpers import ROUTE_AVOID, ROUTE_COMMUNICATE, ROUTE_CONTROL, play


def internal(engine, game_id: str) -> dict:
    return engine.get_state(game_id, include_internal=True)["state"]


def test_route_communicate_ends_romance(engine):
    game_id, last, history = play(engine, ROUTE_COMMUNICATE)
    assert last["ending"] is not None, f"没有收束，最后一轮: {last['dialogue']!r}"
    state = internal(engine, game_id)
    assert state["facts"]["misunderstanding_resolved"], "误会没有被解开"
    assert state["facts"]["class_change_discussed"], "没有认真谈过分班"
    assert state["facts"]["player_expressed_romance"], "玩家没有表达过心意"
    assert state["npc"]["mutual_intent"] == "romance"
    assert state["ending_id"] == "romance"
    assert last["ending"]["id"] == "romance"
    assert last["ending"]["title"] == "下学期，也一起走吧"


def test_route_control_ends_friends(engine):
    """越界干预会被记录、尊重值当场下降；她把选择权要回去之后，关系停在朋友。"""
    from tests.helpers import send

    start = engine.start()
    game_id = start["game_id"]
    send(engine, game_id, ROUTE_CONTROL[0])
    send(engine, game_id, ROUTE_CONTROL[1])

    state = internal(engine, game_id)
    assert state["facts"]["player_controlling"], "越界干预没有被记录"
    assert state["relationship"]["respect_for_autonomy"] <= 40, "尊重值没有因干预下降"

    last = None
    for text in list(ROUTE_CONTROL[2:]) + ["嗯。"] * 12:
        last = send(engine, game_id, text)
        if last.get("ending"):
            break
    assert last is not None and last["ending"] is not None

    state = internal(engine, game_id)
    assert not state["facts"]["player_expressed_romance"], "这条路线不该替玩家表白"
    assert state["npc"]["mutual_intent"] == "friendship"
    assert state["ending_id"] == "friends"
    assert last["ending"]["title"] == "还是和以前一样"


def test_route_avoid_ends_missed(engine):
    game_id, last, history = play(engine, ROUTE_AVOID)
    assert last["ending"] is not None
    state = internal(engine, game_id)
    assert not state["facts"]["misunderstanding_discussed"], "回避路线不该碰到误会"
    assert not state["facts"]["misunderstanding_resolved"]
    assert state["ending_id"] == "missed"


def test_routes_diverge_in_state_not_only_dialogue(engine):
    gid_a, last_a, _ = play(engine, ROUTE_COMMUNICATE)
    gid_b, last_b, _ = play(engine, ROUTE_CONTROL)
    a = internal(engine, gid_a)
    b = internal(engine, gid_b)
    # 不同策略要产生「实际状态差异」，而不是只有对白不同
    assert a["facts"] != b["facts"]
    assert a["relationship"] != b["relationship"]
    assert a["ending_id"] != b["ending_id"]
    assert a["facts"]["player_expressed_romance"] is True
    assert b["facts"]["player_expressed_romance"] is False
    assert a["ending_id"] == "romance"
    assert b["ending_id"] == "friends"


def test_storylets_are_not_repeated(engine):
    game_id, last, _ = play(engine, ROUTE_COMMUNICATE)
    state = internal(engine, game_id)
    assert len(state["used_storylets"]) == len(set(state["used_storylets"]))


def test_turn_budget_is_respected(engine):
    game_id, last, history = play(engine, ROUTE_COMMUNICATE)
    state = internal(engine, game_id)
    assert state["turn_index"] <= state["budget"]["hard_end_at"]
    assert state["ending_phase"] == "committed"
