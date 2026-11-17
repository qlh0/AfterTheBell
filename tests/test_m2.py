"""M2：导演决策、建议回复、语气兜底。"""

from __future__ import annotations

import json

import httpx
import pytest

from app import config
from app import game_state as gs
from app.agents import llm_character
from app.content import load_content
from app.engine import Engine
from app.narrative import director_llm, scheduler
from app.narrative.director_llm import DirectorChoice
from app.rules import suggestions as suggestion_rules


@pytest.fixture(scope="module")
def content():
    return load_content()


@pytest.fixture()
def llm_mode(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODE", "llm")
    monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(config, "LLM_MODEL", "test-model")
    monkeypatch.setattr(config, "LLM_MAX_RETRIES", 1)


def _state(content, **overrides) -> dict:
    state = gs.default_state("g_dir", content.goal_ids(), content.budget())
    state.update(overrides)
    return state


def _director_response(choice: str, reason: str = "测试") -> dict:
    return {
        "choices": [{"message": {"content": json.dumps({"choice": choice, "reason": reason},
                                                        ensure_ascii=False)}}],
        "usage": {"prompt_tokens": 300, "completion_tokens": 20},
    }


# ---------------- 导演 ----------------

def test_director_selects_allowed_candidate(content, monkeypatch, llm_mode):
    state = _state(content, meaningful_turns=6, turn_index=6)
    eligible = content.storylets.eligible(state)
    assert eligible, "这个状态应该有候选事件"
    target = eligible[0].id

    monkeypatch.setattr(director_llm, "_post", lambda messages: _director_response(target))
    choice = director_llm.choose(state, eligible, content, why="turn")

    assert choice.source == "llm"
    assert choice.storylet_id == target
    assert choice.model == "test-model"
    assert choice.prompt_tokens == 300


def test_director_can_choose_no_event(content, monkeypatch, llm_mode):
    state = _state(content, meaningful_turns=6, turn_index=6)
    eligible = content.storylets.eligible(state)
    monkeypatch.setattr(director_llm, "_post", lambda messages: _director_response("no_event"))
    choice = director_llm.choose(state, eligible, content)
    assert choice.source == "llm"
    assert choice.storylet_id is None


def test_director_rejects_unknown_choice(content, monkeypatch, llm_mode):
    state = _state(content, meaningful_turns=6, turn_index=6)
    eligible = content.storylets.eligible(state)
    monkeypatch.setattr(director_llm, "_post",
                        lambda messages: _director_response("summon_dragon"))
    choice = director_llm.choose(state, eligible, content)
    # 非法选择会被拒绝，最终退回确定性打分
    assert choice.source == "fallback"
    assert choice.error == "choice_not_allowed"


def test_director_timeout_falls_back(content, monkeypatch, llm_mode):
    state = _state(content, meaningful_turns=6, turn_index=6)
    eligible = content.storylets.eligible(state)

    def boom(messages):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(director_llm, "_post", boom)
    choice = director_llm.choose(state, eligible, content)
    assert choice.source == "fallback"
    assert choice.error == "timeout"
    assert choice.storylet_id  # 确定性打分仍会给出一个


def test_director_disabled_uses_deterministic(content, monkeypatch):
    monkeypatch.setattr(config, "DIRECTOR_ENABLED", False)
    state = _state(content, meaningful_turns=6, turn_index=6)
    eligible = content.storylets.eligible(state)
    choice = director_llm.choose(state, eligible, content)
    assert choice.source == "deterministic"


def test_stale_choice_is_dropped(content):
    """选完之后状态版本变了：调度器必须丢弃这个决定。"""
    state = _state(content, meaningful_turns=6, turn_index=6)
    library = content.storylets
    eligible = library.eligible(state)
    target = eligible[0].id

    def chooser(st, el):
        st["state_version"] += 1  # 模拟"决定还没提交，状态先变了"
        return DirectorChoice(storylet_id=target, reason="测试", source="llm")

    plan = scheduler.plan_next(state, library, "storylet_resolved", chooser=chooser)
    assert plan.status == "skipped"
    assert plan.reason == "候选在提交前失效"
    assert state["scheduled_storylet"] is None


def test_scheduler_records_planning_turn_even_on_no_event(content):
    state = _state(content, meaningful_turns=6, turn_index=6)
    library = content.storylets
    plan = scheduler.plan_next(
        state, library, "storylet_resolved",
        chooser=lambda st, el: DirectorChoice(storylet_id=None, reason="先不演", source="llm"),
    )
    assert plan.status == "skipped"
    assert plan.reason == "导演选择 no_event"
    assert state["last_plan_turn"] == 6


def test_engine_records_director_metrics(engine, monkeypatch):
    """引擎在关键节点调用导演，并把导演调用写进 llm_calls。"""
    called = {"n": 0}

    def fake_choose(state, eligible, content=None, db=None, game_id=None, why=""):
        called["n"] += 1
        return DirectorChoice(storylet_id=None, reason="先不演", source="llm",
                              model="test-model", latency_ms=12,
                              prompt_tokens=200, completion_tokens=10)

    monkeypatch.setattr("app.engine.director_llm.choose", fake_choose)
    monkeypatch.setattr("app.narrative.director.should_plan", lambda state, reason: (True, "测试强制规划"))

    start = engine.start()
    engine.interact(start["game_id"], "你最近是不是在躲我？", "req_dir_0000001")

    assert called["n"] == 1, "规划点应该调用导演"
    metrics = engine.db.llm_metrics(start["game_id"])
    assert metrics["calls"] >= 1
    events = engine.get_events(start["game_id"])["events"]
    assert any(e["kind"] == "director" for e in events), "导演决策应写进事件日志"


# ---------------- 建议回复 ----------------

def test_suggestions_new_game_mentions_asking_about_distance(content):
    state = _state(content)
    items = suggestion_rules.suggestions(state)
    ids = [i["id"] for i in items]
    assert "ask_distance" in ids
    assert 1 <= len(items) <= suggestion_rules.MAX_SUGGESTIONS
    assert all(i["text"].strip() for i in items)


def test_suggestions_during_finale_are_about_relationship(content):
    state = _state(content, scene="school_gate", meaningful_turns=11)
    storylet = content.storylets.get("school_gate_finale")
    items = suggestion_rules.suggestions(state, storylet)
    ids = [i["id"] for i in items]
    assert {"confess", "friends", "wait"} & set(ids)
    assert len(items) <= suggestion_rules.MAX_SUGGESTIONS


def test_suggestions_are_unique_and_capped(content):
    state = _state(content, scene="school_gate", meaningful_turns=11)
    items = suggestion_rules.suggestions(state, content.storylets.get("school_gate_finale"))
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids))
    assert len(ids) <= 4


def test_suggestions_always_have_fallback(content):
    # 所有事实都做完、关系良好、还没收尾：仍然要给出可接的话
    state = _state(content)
    state["facts"].update({
        "player_asked_distance": True,
        "misunderstanding_discussed": True,
        "misunderstanding_resolved": True,
        "class_change_discussed": True,
        "player_expressed_romance": True,
    })
    state["relationship"]["trust"] = 70
    items = suggestion_rules.suggestions(state)
    assert len(items) >= 2


# ---------------- 语气兜底 ----------------

def _char_response(dialogue: str) -> dict:
    return {
        "choices": [{"message": {"content": json.dumps({
            "dialogue": dialogue, "emotion": "guarded",
            "actions": [], "storylet_outcome": None}, ensure_ascii=False)}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }


def test_harsh_line_is_rewritten(engine, llm_mode, monkeypatch):
    calls = {"n": 0}

    def fake_post(messages):
        calls["n"] += 1
        if calls["n"] == 1:
            return _char_response("关你什么事，少管我。")
        return _char_response("我没事。……你怎么还没走？")

    monkeypatch.setattr(llm_character, "_post", fake_post)
    start = engine.start()
    data = engine.interact(start["game_id"], "你最近是不是在躲我？", "req_harsh_000001")

    assert calls["n"] == 2, "刻薄台词应该触发一次重写"
    assert "少管" not in data["dialogue"]
    assert data["dialogue"] == "我没事。……你怎么还没走？"


def test_harsh_line_falls_back_if_still_harsh(engine, llm_mode, monkeypatch):
    monkeypatch.setattr(llm_character, "_post",
                        lambda messages: _char_response("关你什么事。"))
    start = engine.start()
    data = engine.interact(start["game_id"], "你最近是不是在躲我？", "req_harsh_000002")
    assert data["ui_hints"]["dialogue_source"] == "fallback:too_harsh"
    assert "关你什么事" not in data["dialogue"]
    assert data["dialogue"]
