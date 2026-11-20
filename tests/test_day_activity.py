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
        assert data["presentation"]["scene_id"] == st["scene"]
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
    assert st["active_storylet"] == "library_study", "第二轮仍应在图书馆"
    assert st["scene"] == "library"

    engine.interact(gid, "那我们先把这页看完吧。", "req_lib_003")
    st = _state(engine, gid)
    assert st["facts"]["library_visited"] is True
    assert st["scene"] == "library", "结算台词仍应停留在图书馆"
    assert st["active_storylet"] is None

    engine.interact(gid, "我们回校门口吧。", "req_lib_004")
    st = _state(engine, gid)
    assert st["scene"] == "school_gate"


def test_corridor_activity_between_classroom_and_gate(engine):
    start = engine.start()
    gid = start["game_id"]
    engine.interact(gid, "陪我去走廊站一会儿吧。", "req_cor_001")
    st = _state(engine, gid)
    assert st["active_storylet"] == "corridor_chat"
    assert st["scene"] == "corridor"

    engine.interact(gid, "你最近是不是在躲我？", "req_cor_002")
    st = _state(engine, gid)
    assert st["active_storylet"] == "corridor_chat", "第二轮仍应在走廊"
    assert st["scene"] == "corridor"

    engine.interact(gid, "其实我只是有点担心你。", "req_cor_003")
    st = _state(engine, gid)
    assert st["facts"]["corridor_chatted"] is True
    assert st["scene"] == "corridor", "结算台词仍应停留在走廊"

    engine.interact(gid, "我们回校门口吧。", "req_cor_004")
    st = _state(engine, gid)
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
    assert st["active_storylet"] == "shop_trip", "第二轮仍应在小卖部"
    assert st["scene"] == "shop"

    engine.interact(gid, "买两瓶一样的吧，路上喝。", "req_shop_003")
    st = _state(engine, gid)
    assert st["facts"]["shop_visited"] is True
    assert st["scene"] == "shop", "小卖部结束后默认不回校门口"
    assert st["active_storylet"] is None

    engine.interact(gid, "我们回校门口吧。", "req_shop_004")
    st = _state(engine, gid)
    assert st["scene"] == "school_gate", "玩家明确说回去时才回校门口"


def test_shop_advance_leaves_shop_for_next_day(engine):
    start = engine.start()
    gid = start["game_id"]
    engine.advance(gid, "req_shop_adv_000", "continue")
    engine.interact(gid, "一起去小卖部买点东西吧。", "req_shop_adv_001")
    for i in range(2):
        engine.interact(gid, "买两瓶一样的吧。", f"req_shop_adv_{i + 2:03d}")
    st = _state(engine, gid)
    assert (st["day"], st["scene"]) == (1, "shop")

    engine.advance(gid, "req_shop_adv_leave", "continue")
    st = _state(engine, gid)
    assert (st["day"], st["scene"]) == (2, "classroom")


def test_class_change_evasion_is_detected():
    from app.agents.llm_character import _has_class_plan, _is_evasive_class, _needs_class_plan
    from app.rules import meaningful_turn

    analysis = meaningful_turn.analyze("分班的事，你是怎么想的？")
    assert "class_change" in analysis.topics
    assert _is_evasive_class("随便报个呗，你查户口啊？", analysis)
    assert not _is_evasive_class("我填了理重点班，我想了很久。", analysis)
    assert _needs_class_plan(analysis)
    assert not _has_class_plan("还是这学校啊，还能去哪。")
    assert _has_class_plan("我填了理重点班，我想了很久。")


def test_goodbye_at_gate_moves_to_next_day(engine):
    start = engine.start()
    gid = start["game_id"]
    engine.advance(gid, "req_bye_000", "continue")
    state = _state(engine, gid)
    # 清掉排期，专门验证「明天见」本身就能收束
    state["active_storylet"] = None
    state["scheduled_storylet"] = None
    state["state_version"] += 1
    engine.db.save_state(state)

    data = engine.interact(gid, "那明天见啦。", "req_bye_001")
    st = _state(engine, gid)
    assert (st["day"], st["scene"]) == (2, "classroom")
    assert any("明天放学后见" in line for line in data["narration"])
    assert all("第二天放学后" not in line for line in data["narration"])

    data2 = engine.interact(gid, "嗯，我记住了。", "req_bye_002")
    assert any("第二天放学后" in line for line in data2["narration"])


def test_proactive_next_day_at_turn_15(engine):
    start = engine.start()
    gid = start["game_id"]
    state = _state(engine, gid)
    state["day"] = 1
    state["scene"] = "school_gate"
    state["turn_index"] = 14
    state["active_storylet"] = None
    state["scheduled_storylet"] = None
    state["state_version"] += 1
    engine.db.save_state(state)

    data = engine.interact(gid, "嗯。", "req_proactive_001")
    st = _state(engine, gid)
    assert (st["day"], st["scene"]) == (2, "classroom")
    assert any("明天放学后见" in line for line in data["narration"])


def test_stalling_dialogue_is_detected():
    from app.agents.llm_character import _is_stalling

    assert _is_stalling("没什么……刚想说的话，到嘴边又忘了。")
    assert not _is_stalling("我填了理重点班，我想了很久。")


def test_class_talk_requires_concrete_plan(engine):
    from app.rules import class_talk
    from app.rules.meaningful_turn import analyze

    start = engine.start()
    state = _state(engine, start["game_id"])
    state["facts"]["class_change_discussed"] = False
    analysis = analyze("分班的事，你是怎么想的？")
    assert class_talk.commit(state, analysis, "就，填了张表呗。") == []
    changes = class_talk.commit(state, analysis, "我填了理重点班，我想了很久。")
    assert changes
    assert state["facts"]["class_change_discussed"] is True


def test_activity_chips_respect_scene_and_used(engine):
    start = engine.start()
    gid = start["game_id"]
    start_ids = {item["id"] for item in start["suggestions"]}
    assert {"library", "corridor"} <= start_ids

    engine.interact(gid, "陪我去走廊站一会儿吧。", "req_chip_001")
    engine.interact(gid, "你最近是不是在躲我？", "req_chip_002")
    engine.interact(gid, "其实我只是有点担心你。", "req_chip_003")
    engine.interact(gid, "我们回校门口吧。", "req_chip_004")
    st = _state(engine, gid)
    # 已经用过走廊，不再出现；此时已回到校门口，应有小卖部提示
    chips = {item["id"] for item in suggestion_rules.suggestions(st)}
    assert "corridor" not in chips
    assert "shop" in chips
    assert st["scene"] == "school_gate"


def test_activities_are_available_on_day2(engine):
    # 第二天教室：图书馆/走廊仍可用
    start = engine.start()
    gid = start["game_id"]
    engine.advance(gid, "req_day2_001", "continue")
    engine.advance(gid, "req_day2_002", "continue")
    st = _state(engine, gid)
    assert (st["day"], st["scene"]) == (2, "classroom")
    ids = {item["id"] for item in suggestion_rules.suggestions(st)}
    assert {"library", "corridor"} <= ids

    data = engine.interact(gid, "放学后要不要一起去图书馆学习？", "req_day2_003")
    st = _state(engine, gid)
    assert st["day"] == 2
    assert st["active_storylet"] == "library_study"
    assert st["scene"] == "library"
    assert data["presentation"]["scene_id"] == "library"

    # 第二天校门口：小卖部仍可用
    start2 = engine.start()
    gid2 = start2["game_id"]
    for i in range(3):
        engine.advance(gid2, f"req_day2s_{i:02d}", "continue")
    st = _state(engine, gid2)
    assert (st["day"], st["scene"]) == (2, "school_gate")
    engine.interact(gid2, "一起去小卖部买点东西吧。", "req_day2s_shop")
    st = _state(engine, gid2)
    assert st["active_storylet"] == "shop_trip"
    assert st["scene"] == "shop"


def test_new_expression_sprites_are_mapped():
    from app import game_state as gs

    assert gs.sprite_for("shy") == "xuzhi_shy"
    assert gs.sprite_for("surprised") == "xuzhi_surprised"


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
