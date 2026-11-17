"""M3：指标、边界与兜底收束。"""

from __future__ import annotations

import pytest

from app import config
from app import game_state as gs
from app.content import load_content


@pytest.fixture(scope="module")
def content():
    return load_content()


def _filler_turns(n: int) -> list[str]:
    return ["嗯。"] * n


# ---------------- 指标 ----------------

def test_llm_stats_percentiles(engine):
    start = engine.start()
    gid = start["game_id"]
    for latency in (100, 200, 300, 400):
        engine.db.add_llm_call(gid, "character", "m", latency, 100, 20, ok=True)
    engine.db.add_llm_call(gid, "director", "m", 900, 300, 15, ok=False, error="timeout")
    engine.db.add_llm_call(gid, "director", "m", 500, 250, 12, ok=True)

    stats = engine.get_metrics(gid)
    char = stats["by_purpose"]["character"]
    assert char["calls"] == 4
    assert char["p50_latency_ms"] == 200
    assert char["p95_latency_ms"] == 400
    assert char["max_latency_ms"] == 400
    assert char["prompt_tokens"] == 400
    assert char["failures"] == 0

    director = stats["by_purpose"]["director"]
    assert director["calls"] == 2
    assert director["failures"] == 1
    assert director["errors"]["timeout"] == 1

    assert stats["totals"]["calls"] == 6
    assert stats["totals"]["failures"] == 1
    assert stats["errors"] == {"timeout": 1}
    assert stats["session"]["turn_index"] == 0


def test_metrics_endpoint(client):
    game_id = client.post("/game/start").json()["game_id"]
    data = client.get(f"/game/{game_id}/metrics").json()
    assert data["game_id"] == game_id
    assert data["totals"]["calls"] == 0
    assert data["session"]["ending_phase"] == "none"
    assert "budget" in data["session"]


# ---------------- 边界：沉默 / 刷屏 ----------------

def test_silence_input_does_not_crash(engine):
    start = engine.start()
    gid = start["game_id"]
    data = engine.interact(gid, "……", "req_silence_0001")
    assert data["dialogue"]
    assert data["state_version"] == 1
    assert data["ui_hints"]["meaningful"] is False


def test_endless_filler_still_ends(engine):
    """玩家只回「嗯」也不能无限聊：到达硬上限必须收束。"""
    start = engine.start()
    gid = start["game_id"]
    ending = None
    for i in range(40):
        data = engine.interact(gid, "嗯。", f"req_filler_{i:04d}")
        if data.get("ending"):
            ending = data["ending"]
            break
    assert ending is not None, "40 轮闲聊后仍然没有收束"
    state = engine.get_state(gid, include_internal=True)["state"]
    assert state["ending_phase"] == "committed"
    # 纯闲聊也会在硬上限附近被强制收束（不再拖到两倍回合）
    assert state["turn_index"] <= state["budget"]["hard_end_at"] + 2


def test_disabled_storylets_still_reach_an_ending(engine, monkeypatch):
    """消融对照组：关掉 Storylet 也要能收束（走兜底结局）。"""
    monkeypatch.setattr(config, "STORYLETS_ENABLED", False)
    start = engine.start()
    gid = start["game_id"]
    ending = None
    for i, text in enumerate(["你最近是不是在躲我？", "我喜欢你。"] + _filler_turns(30)):
        data = engine.interact(gid, text, f"req_nost_{i:04d}")
        if data.get("ending"):
            ending = data["ending"]
            break
    assert ending is not None
    events = engine.get_events(gid)["events"]
    assert not any(e["kind"] == "storylet" for e in events)
    assert any(e["event_id"] == "forced_finale" for e in events)


# ---------------- 背景交代（玩家不该靠猜） ----------------

def test_opening_explains_background(engine):
    start = engine.start()
    joined = "".join(start["narration"])
    assert "回消息" in joined, "开场要交代她最近的疏远"
    assert "分班意向表" in joined, "开场要让玩家看到分班表这条线索"
    assert "高中谈恋爱很麻烦" in joined, "开场要交代玩家说过的那句话"


def test_storylets_carry_exposition(content):
    late = content.storylets.get("late_explanation")
    klass = content.storylets.get("class_choice")
    assert late is not None and late.exposition, "「那句话」事件要自带背景旁白"
    assert any("高中谈恋爱很麻烦" in line for line in late.exposition + (late.opening_cue,))
    assert klass is not None and klass.exposition, "分班事件要自带背景旁白"


def test_exposition_is_shown_when_event_activates(engine, monkeypatch):
    """事件激活时，背景旁白要一起进入 narration。"""
    from app.narrative import scheduler as sched

    start = engine.start()
    gid = start["game_id"]
    state = engine.db.load_state(gid)
    state["scheduled_storylet"] = "late_explanation"
    state["facts"]["misunderstanding_discussed"] = True
    state["meaningful_turns"] = 4
    state["state_version"] = 3
    engine.db.save_state(state, snapshot=False)

    data = engine.interact(gid, "我那天真的不是在说你。", "req_expo_0000001")
    assert any("高中谈恋爱很麻烦" in line for line in data["narration"])
    # 玩家已经解释过：事件可以在同一轮直接收束，但背景旁白必须先出现
    resolved = [e for e in engine.get_events(gid)["events"]
                if e["event_id"] == "late_explanation" and e["status"] == "resolved"]
    assert data["active_event_id"] == "late_explanation" or resolved


# ---------------- 指标不影响玩家可见层 ----------------

def test_metrics_are_not_leaked_to_player(engine):
    start = engine.start()
    gid = start["game_id"]
    data = engine.interact(gid, "你最近是不是在躲我？", "req_leak_000001")
    blob = str(data)
    for forbidden in ("llm_calls", "p95", "prompt_tokens", "by_purpose"):
        assert forbidden not in blob
