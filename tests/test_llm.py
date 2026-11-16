"""M1 角色 Agent 的单元测试：解析、校验、兜底、指标。

全部用假的 `_post`，不打真实 API。
"""

from __future__ import annotations

import json

import httpx
import pytest

from app import config
from app import game_state as gs
from app.agents import llm_character, mock_character
from app.content import load_content
from app.rules.meaningful_turn import analyze


@pytest.fixture()
def llm_mode(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODE", "llm")
    monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(config, "LLM_MODEL", "test-model")
    monkeypatch.setattr(config, "LLM_MAX_RETRIES", 1)


def _response(payload: dict, prompt_tokens: int = 120, completion_tokens: int = 30) -> dict:
    return {
        "choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


def _state() -> dict:
    content = load_content()
    return gs.default_state("g_test", content.goal_ids(), content.budget())


# ---------------- 引擎级：真用 LLM 的分支 ----------------

def test_engine_uses_llm_dialogue(engine, llm_mode, monkeypatch):
    captured: dict = {}

    def fake_post(messages):
        captured["messages"] = messages
        return _response({"dialogue": "……你怎么还没走？", "emotion": "guarded",
                          "actions": [], "storylet_outcome": None})

    monkeypatch.setattr(llm_character, "_post", fake_post)
    start = engine.start()
    data = engine.interact(start["game_id"], "你最近是不是在躲我？", "req_llm_0000001")

    assert data["dialogue"] == "……你怎么还没走？"
    assert data["ui_hints"]["dialogue_source"] == "llm"
    assert data["ui_hints"]["llm"]["model"] == "test-model"
    metrics = engine.db.llm_metrics(start["game_id"])
    assert metrics["calls"] == 1
    assert metrics["failures"] == 0
    # prompt 里必须包含玩家这句话与角色设定
    prompt = captured["messages"][-1]["content"]
    assert "你最近是不是在躲我" in prompt
    assert "许栀" in captured["messages"][0]["content"]


def test_bad_json_falls_back(engine, llm_mode, monkeypatch):
    monkeypatch.setattr(llm_character, "_post",
                        lambda messages: {"choices": [{"message": {"content": "抱歉，我不能回答"}}], "usage": {}})
    start = engine.start()
    data = engine.interact(start["game_id"], "你最近是不是在躲我？", "req_llm_0000002")

    assert data["ui_hints"]["dialogue_source"].startswith("fallback:bad_json")
    assert data["dialogue"], "兜底也必须有一句台词"
    assert engine.db.llm_metrics(start["game_id"])["failures"] == 1


def test_timeout_falls_back(engine, llm_mode, monkeypatch):
    def boom(messages):
        raise httpx.TimeoutException("read timeout")

    monkeypatch.setattr(llm_character, "_post", boom)
    start = engine.start()
    data = engine.interact(start["game_id"], "你最近是不是在躲我？", "req_llm_0000003")
    assert data["ui_hints"]["dialogue_source"].startswith("fallback:timeout")
    assert data["dialogue"]


def test_leaked_internal_info_falls_back(engine, llm_mode, monkeypatch):
    monkeypatch.setattr(llm_character, "_post", lambda messages: _response({
        "dialogue": "我的好感度是 60，你再加把劲。", "emotion": "normal",
        "actions": [], "storylet_outcome": None,
    }))
    start = engine.start()
    data = engine.interact(start["game_id"], "你好。", "req_llm_0000004")
    assert "好感度" not in data["dialogue"]
    assert data["ui_hints"]["dialogue_source"].startswith("fallback:leak")


def test_rule_actions_commit_even_if_llm_silent(engine, llm_mode, monkeypatch):
    """模型不给动作，玩家真实表达过的心意仍然要提交（规则为准）。"""
    monkeypatch.setattr(llm_character, "_post", lambda messages: _response({
        "dialogue": "……你别开这种玩笑。", "emotion": "guarded",
        "actions": [], "storylet_outcome": None,
    }))
    start = engine.start()
    engine.interact(start["game_id"], "我喜欢你。", "req_llm_0000005")
    state = engine.get_state(start["game_id"], include_internal=True)["state"]
    assert state["facts"]["player_expressed_romance"] is True


# ---------------- 校验层 ----------------

def test_llm_actions_need_evidence():
    analysis = analyze("你好。")
    parsed = {"dialogue": "嗯。", "emotion": "normal",
              "actions": ["express_romance", "small_talk"], "storylet_outcome": None}
    reply = llm_character._validate(parsed, _state(), analysis, None)
    assert reply.source == "llm"
    assert "express_romance" not in reply.actions, "玩家没说喜欢，就不能替玩家记成表白"


def test_llm_actions_accepted_with_evidence():
    analysis = analyze("我喜欢你，很久了。")
    parsed = {"dialogue": "……你、你说什么。", "emotion": "soft",
              "actions": ["express_romance"], "storylet_outcome": None}
    reply = llm_character._validate(parsed, _state(), analysis, None)
    assert reply.actions == ["express_romance"]


def test_llm_outcome_must_be_allowed():
    content = load_content()
    storylet = content.storylets.get("late_explanation")
    analysis = analyze("我那天是在说陈屿他们班，真的不是说你。")
    state = _state()

    ok = llm_character._validate(
        {"dialogue": "原来是这样。", "actions": [], "storylet_outcome": "clarified"},
        state, analysis, storylet,
    )
    assert ok.storylet_outcome == "clarified"

    bad = llm_character._validate(
        {"dialogue": "原来是这样。", "actions": [], "storylet_outcome": "instant_romance"},
        state, analysis, storylet,
    )
    assert bad.storylet_outcome is None
    assert "outcome_not_allowed" in bad.notes


def test_empty_dialogue_falls_back(engine, llm_mode, monkeypatch):
    monkeypatch.setattr(llm_character, "_post", lambda messages: _response({
        "dialogue": "   ", "emotion": "normal", "actions": [], "storylet_outcome": None,
    }))
    start = engine.start()
    data = engine.interact(start["game_id"], "你好。", "req_llm_0000006")
    assert data["dialogue"]
    assert data["ui_hints"]["dialogue_source"].startswith("fallback:empty_dialogue")


def test_prompt_has_no_internal_numbers():
    """prompt 里不出现原始数值，避免模型把数字说漏嘴。"""
    from app.agents import prompts

    content = load_content()
    state = _state()
    state["relationship"] = {"affection": 63, "trust": 71, "respect_for_autonomy": 58}
    analysis = analyze("你最近是不是在躲我？")
    text = prompts.user_prompt(state, analysis, None, content, [], [])
    for number in ("63", "71", "58"):
        assert number not in text
