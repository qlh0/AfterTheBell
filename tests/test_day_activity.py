"""两天场景、插曲事件与 22 轮硬收束。"""

from __future__ import annotations

from app.engine import Engine
from app.rules import suggestions as suggestion_rules


def _state(engine: Engine, gid: str) -> dict:
    return engine.get_state(gid, include_internal=True)["state"]


def test_advance_cycles_all_four_required_scenes(engine):
    start = engine.start()
    gid = start["game_id"]
    seen = [(1, "classroom")]
    for i in range(3):
        data = engine.advance(gid, f"req_day_{i:02d}", "continue")
        st = _state(engine, gid)
        seen.append((st["day"], st["scene"]))
        assert data["presentation"]["day"] == st["day"]
        assert data["presentation"]["scene_id"] in {
            st["scene"], f"{st['scene']}_day2"
        }
    assert seen == [
        (1, "classroom"),
        (1, "school_gate"),
        (2, "classroom"),
        (2, "school_gate"),
    ]


def test_auto_progress_shows_day1_gate_day2_classroom_and_gate(engine):
    start = engine.start()
    gid = start["game_id"]
    seen = set()
    for i in range(24):
        data = engine.interact(gid, "嗯。", f"req_auto_{i:03d}")
        st = _state(engine, gid)
        seen.add((st["day"], st["scene"]))
        if data.get("ending"):
            break
    assert (1, "school_gate") in seen
    assert (2, "classroom") in seen
    assert (2, "school_gate") in seen
    # 第四天校门口之后不再回到第一天
    assert all((day, scene) in {
        (1, "classroom"), (1, "school_gate"),
        (2, "classroom"), (2, "school_gate"),
    } for day, scene in seen)


def test_library_activity_from_suggestion_text(engine):
    start = engine.start()
    gid = start["game_id"]
    ids = {item["id"] for item in start["suggestions"]}
    assert "library" in ids
    data = engine.interact(gid, "放学后要不要一起去图书馆学习？", "req_lib_001")
    st = _state(engine, gid)
    assert st["active_storylet"] == "library_study"
    assert st["scene"] == "library"
    assert data["presentation"]["scene_id"] == "library"

    engine.interact(gid, "这道题你会吗？", "req_lib_002")
    st = _state(engine, gid)
    assert st["facts"]["library_visited"] is True
    assert st["scene"] == "school_gate"
    assert st["active_storylet"] is None


def test_corridor_activity_between_classroom_and_gate(engine):
    start = engine.start()
    gid = start["game_id"]
    engine.interact(gid, "陪我去走廊站一会儿吧。", "req_cor_001")
    st = _state(engine, gid)
    assert st["active_storylet"] == "corridor_chat"
    assert st["scene"] == "corridor"

    engine.interact(gid, "你最近是不是在躲我？", "req_cor_002")
    st = _state(engine, gid)
    assert st["facts"]["corridor_chatted"] is True
    assert st["scene"] == "school_gate"


def test_shop_activity_after_gate(engine):
    start = engine.start()
    gid = start["game_id"]
    engine.advance(gid, "req_shop_000", "continue")
    data = engine.interact(gid, "一起去小卖部买点东西吧。", "req_shop_001")
    st = _state(engine, gid)
    assert st["active_storylet"] == "shop_trip"
    assert st["scene"] == "shop"
    assert data["presentation"]["scene_id"] == "shop"

    engine.interact(gid, "你想喝什么？我请你。", "req_shop_002")
    st = _state(engine, gid)
    assert st["facts"]["shop_visited"] is True
    assert st["scene"] == "school_gate"


def test_activity_chips_respect_scene_and_used(engine):
    start = engine.start()
    gid = start["game_id"]
    start_ids = {item["id"] for item in start["suggestions"]}
    assert {"library", "corridor"} <= start_ids

    engine.interact(gid, "陪我去走廊站一会儿吧。", "req_chip_001")
    engine.interact(gid, "你最近是不是在躲我？", "req_chip_002")
    st = _state(engine, gid)
    # 已经用过走廊，不再出现；此时已回到校门口，应有小卖部提示
    chips = {item["id"] for item in suggestion_rules.suggestions(st)}
    assert "corridor" not in chips
    assert "shop" in chips
    assert st["scene"] == "school_gate"


def test_hard_cap_ends_at_22_with_closure_and_day2_gate(engine):
    start = engine.start()
    gid = start["game_id"]
    last = None
    for i in range(30):
        last = engine.interact(gid, "嗯。", f"req_cap_{i:03d}")
        if last.get("ending"):
            break
    st = _state(engine, gid)
    assert st["turn_index"] == 22
    assert st["ending_phase"] == "committed"
    assert st["day"] == 2
    assert st["scene"] == "school_gate"
    assert last["ending"] is not None
    assert last["dialogue"]
    assert any("她" in line or "最后" in line for line in last.get("narration", []))
    events = engine.get_events(gid)["events"]
    assert any(e["event_id"] == "school_gate_finale" for e in events) or any(
        e["event_id"] == "forced_finale" for e in events)
