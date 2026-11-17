"""v0.3.1：分班只讲一次、回忆必须有钩子、事件之间留呼吸、预算延长。"""

from __future__ import annotations

import pytest

from app import game_state as gs
from app.content import load_content
from app.rules import threads
from app.rules.storylet_progress import initial_evidence


@pytest.fixture(scope="module")
def content():
    return load_content()


def _state(content) -> dict:
    state = gs.default_state("g_patch", content.goal_ids(), content.budget())
    threads.sync(state)
    return state


def test_budget_is_14(content):
    assert content.budget() == 14
    state = _state(content)
    assert state["budget"]["soft_end_at"] == 11
    assert state["budget"]["hard_end_at"] == 17


def test_class_talk_blocks_class_choice(engine):
    start = engine.start()
    gid = start["game_id"]
    engine.interact(gid, "分班的事，你是怎么想的？", "req_patch_000001")
    state = engine.get_state(gid, include_internal=True)["state"]
    assert state["facts"]["class_change_discussed"] is True
    assert state["active_storylet"] != "class_choice"
    assert state["scheduled_storylet"] != "class_choice"

    # 之后不会再触发分班事件
    engine.interact(gid, "那你填的是哪个班？", "req_patch_000002")
    after = engine.get_state(gid, include_internal=True)["state"]
    assert after["active_storylet"] != "class_choice"
    assert after["scheduled_storylet"] != "class_choice"


def test_shared_memory_requires_player_hook(content):
    state = _state(content)
    state["meaningful_turns"] = 6
    state["facts"]["old_note_seen"] = True
    ids = {s.id for s in content.storylets.eligible(state)}
    assert "shared_memory" not in ids

    state["facts"]["player_mentioned_memory"] = True
    ids = {s.id for s in content.storylets.eligible(state)}
    assert "shared_memory" in ids


def test_shared_memory_picks_concrete_anchor(engine):
    start = engine.start()
    gid = start["game_id"]
    state = engine.db.load_state(gid)
    state["facts"]["old_note_seen"] = True
    state["facts"]["player_mentioned_memory"] = True
    state["meaningful_turns"] = 6
    state["scheduled_storylet"] = "shared_memory"
    state["state_version"] += 1
    engine.db.save_state(state)

    data = engine.interact(gid, "我还记得那张便签。", "req_patch_000003")
    joined = "".join(data["narration"])
    assert "便签" in joined, "回忆事件必须点名具体的那段回忆"
    assert "一件小事" not in joined


def test_event_cooldown_gives_one_quiet_turn(engine):
    start = engine.start()
    gid = start["game_id"]
    state = engine.db.load_state(gid)
    storylet = engine.content.storylets.get("late_explanation")
    state["active_storylet"] = "late_explanation"
    state["storylet_stage"] = "active"
    state["storylet_evidence"] = initial_evidence(storylet, state)
    state["storylet_evidence"]["quote_raised"] = True
    state["facts"]["misunderstanding_discussed"] = True
    state["relationship"]["trust"] = 50
    state["state_version"] += 1
    engine.db.save_state(state)

    engine.interact(gid, "我说的那句话不是那个意思，我是说陈屿他们班。", "req_patch_000004")
    after = engine.get_state(gid, include_internal=True)["state"]
    assert after["last_storylet_resolved_turn"] >= 0
    assert after["scheduled_storylet"] is None, "事件刚结束不应立刻排下一个事件"


def test_class_talk_does_not_fire_when_she_deflects(engine, monkeypatch):
    import json

    from app import config
    from app.agents import llm_character

    monkeypatch.setattr(config, "LLM_MODE", "llm")
    monkeypatch.setattr(config, "LLM_API_KEY", "test")
    monkeypatch.setattr(config, "LLM_MAX_RETRIES", 0)

    def fake_post(messages):
        return {"choices": [{"message": {"content": json.dumps({
            "dialogue": "分班啊……还没想好，以后再说吧。", "emotion": "guarded",
            "actions": [], "storylet_outcome": None, "npc_intent": None,
        }, ensure_ascii=False)}}], "usage": {"prompt_tokens": 10, "completion_tokens": 10}}

    monkeypatch.setattr(llm_character, "_post", fake_post)
    start = engine.start()
    gid = start["game_id"]
    engine.interact(gid, "分班的事，你是怎么想的？", "req_patch_000005")

    state = engine.get_state(gid, include_internal=True)["state"]
    assert state["facts"]["class_change_discussed"] is False
