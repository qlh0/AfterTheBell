"""P1/P2：线索、NPC 主动意图、JSON 驱动的目标、新事件与结局一致性。"""

from __future__ import annotations

import json

import pytest

from app import config
from app import game_state as gs
from app.agents import llm_character
from app.content import load_content
from app.narrative import director_llm
from app.narrative.storylets import StoryletLibrary
from app.rules import endings, goals, threads
from app.rules.storylet_progress import initial_evidence


@pytest.fixture(scope="module")
def content():
    return load_content()


@pytest.fixture()
def llm_mode(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODE", "llm")
    monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(config, "LLM_MODEL", "test-model")
    monkeypatch.setattr(config, "LLM_MAX_RETRIES", 0)


def _state(content) -> dict:
    state = gs.default_state("g_dyn", content.goal_ids(), content.budget())
    threads.sync(state)
    return state


# ---------------- 线索 ----------------

def test_threads_start_open_and_progress(content):
    state = _state(content)
    status = {t["id"]: t["status"] for t in state["open_threads"]}
    assert set(status) == {"distance_between_us", "misunderstanding_quote", "class_change_future"}
    assert set(status.values()) == {"open"}

    state["facts"]["player_asked_distance"] = True
    state["facts"]["misunderstanding_discussed"] = True
    threads.sync(state)
    status = {t["id"]: t["status"] for t in state["open_threads"]}
    assert status["distance_between_us"] == "discussed"
    assert status["misunderstanding_quote"] == "partially_clarified"

    state["facts"]["misunderstanding_resolved"] = True
    state["facts"]["class_change_discussed"] = True
    state["relationship"]["respect_for_autonomy"] = 60
    threads.sync(state)
    status = {t["id"]: t["status"] for t in state["open_threads"]}
    assert status["misunderstanding_quote"] == "resolved"
    assert status["class_change_future"] == "discussed"
    assert all(t["evidence"] for t in state["open_threads"])


def test_threads_close_as_unresolved_or_deferred_at_ending(content):
    state = _state(content)
    state["ending_phase"] = "committed"
    threads.sync(state)
    status = {t["id"]: t["status"] for t in state["open_threads"]}
    assert status["distance_between_us"] == "unresolved"
    assert status["misunderstanding_quote"] == "unresolved"
    assert status["class_change_future"] == "deferred"


def test_director_prompt_includes_threads(content):
    state = _state(content)
    messages = director_llm.build_messages(state, [], content, [], [])
    user = messages[-1]["content"]
    assert "未解决的线索" in user
    assert "她为什么疏远你" in user


# ---------------- 目标由 JSON 驱动 ----------------

def test_goals_progress_from_json(content):
    state = _state(content)
    goals.record_goal_progress(state, content)
    assert state["narrative_goals"]["repair_or_deepen_trust"] == "skipped"

    state["facts"]["misunderstanding_discussed"] = True
    goals.record_goal_progress(state, content)
    assert state["narrative_goals"]["clarify_misunderstanding"] == "in_progress"

    state["facts"]["misunderstanding_resolved"] = True
    goals.record_goal_progress(state, content)
    assert state["narrative_goals"]["clarify_misunderstanding"] == "done"


def test_repair_goal_activates_on_conflict(content):
    state = _state(content)
    state["facts"]["player_controlling"] = True
    goals.record_goal_progress(state, content)
    assert state["narrative_goals"]["repair_or_deepen_trust"] == "pending"

    state["relationship"]["trust"] = 60
    state["relationship"]["respect_for_autonomy"] = 55
    goals.record_goal_progress(state, content)
    assert state["narrative_goals"]["repair_or_deepen_trust"] == "done"


# ---------------- 新事件 ----------------

def test_shared_memory_needs_real_shared_experience(content):
    library = content.storylets
    state = _state(content)
    state["meaningful_turns"] = 5
    ids = {s.id for s in library.eligible(state)}
    assert "shared_memory" not in ids

    state["facts"]["old_note_seen"] = True
    ids = {s.id for s in library.eligible(state)}
    assert "shared_memory" not in ids, "只提过便签不够，玩家没提回忆就不该触发"

    state["facts"]["player_mentioned_memory"] = True
    ids = {s.id for s in library.eligible(state)}
    assert "shared_memory" in ids


def test_unfinished_conversation_needs_open_conflict(content):
    state = _state(content)
    state["meaningful_turns"] = 6
    ids = {s.id for s in content.storylets.eligible(state)}
    assert "unfinished_conversation" not in ids

    state["facts"]["misunderstanding_discussed"] = True
    state["facts"]["misunderstanding_resolved"] = False
    ids = {s.id for s in content.storylets.eligible(state)}
    assert "unfinished_conversation" in ids


# ---------------- 结局一致性 ----------------

def test_romance_blocked_when_player_declined(content):
    state = _state(content)
    state["relationship"] = {"affection": 80, "trust": 75, "respect_for_autonomy": 70}
    state["facts"].update({
        "misunderstanding_resolved": True,
        "misunderstanding_discussed": True,
        "class_change_discussed": True,
        "player_expressed_romance": True,
        "player_declined_romance": True,
        "finale_resolved": True,
    })
    state["narrative_goals"]["define_relationship"] = "done"
    state["npc"]["mutual_intent"] = "romance"
    assert endings.pick_ending(state, content) != "romance"


def test_friends_allowed_when_player_chooses_friends(content):
    state = _state(content)
    state["relationship"] = {"affection": 55, "trust": 50, "respect_for_autonomy": 40}
    state["facts"].update({
        "misunderstanding_discussed": True,
        "player_chose_friends": True,
        "player_declined_romance": True,
    })
    state["npc"]["mutual_intent"] = "friendship"
    assert endings.pick_ending(state, content) == "friends"


def test_friends_blocked_when_respect_collapsed(content):
    state = _state(content)
    state["relationship"] = {"affection": 50, "trust": 50, "respect_for_autonomy": 20}
    state["facts"]["misunderstanding_discussed"] = True
    state["npc"]["mutual_intent"] = "declined"
    assert endings.pick_ending(state, content) == "missed"


# ---------------- NPC 主动意图 ----------------

def _llm_payload(dialogue: str, npc_intent: str | None) -> dict:
    return {
        "choices": [{"message": {"content": json.dumps({
            "dialogue": dialogue, "emotion": "guarded", "actions": [],
            "storylet_outcome": None, "npc_intent": npc_intent,
        }, ensure_ascii=False)}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }


def test_npc_can_invite_walk_home(engine, llm_mode, monkeypatch):
    start = engine.start()
    gid = start["game_id"]
    state = engine.db.load_state(gid)
    state["scene"] = "school_gate"
    state["relationship"]["trust"] = 50
    state["state_version"] += 1
    engine.db.save_state(state)

    monkeypatch.setattr(llm_character, "_post",
                        lambda messages: _llm_payload("你今天怎么回去？", "invite_walk_home"))
    engine.interact(gid, "嗯。", "req_npc_0000001")

    after = engine.get_state(gid, include_internal=True)["state"]
    assert after["scheduled_storylet"] == "walk_home"
    events = engine.get_events(gid)["events"]
    assert any(e["kind"] == "npc" and e["payload"].get("intent") == "invite_walk_home" for e in events)


def test_npc_intent_ignored_in_wrong_context(engine, llm_mode, monkeypatch):
    start = engine.start()
    gid = start["game_id"]
    monkeypatch.setattr(llm_character, "_post",
                        lambda messages: _llm_payload("你先走吧。", "invite_walk_home"))
    engine.interact(gid, "嗯。", "req_npc_0000002")
    state = engine.get_state(gid, include_internal=True)["state"]
    assert state["scheduled_storylet"] in (None, "direct_question")


def test_npc_boundary_is_noted_but_not_scheduled(engine, llm_mode, monkeypatch):
    start = engine.start()
    gid = start["game_id"]
    state = engine.db.load_state(gid)
    state["facts"]["player_controlling"] = True
    state["state_version"] += 1
    engine.db.save_state(state)

    monkeypatch.setattr(llm_character, "_post",
                        lambda messages: _llm_payload("这是我的事。", "set_boundary"))
    engine.interact(gid, "你必须听我的。", "req_npc_0000003")

    after = engine.get_state(gid, include_internal=True)["state"]
    assert after["npc"]["last_intent"] == "set_boundary"
    assert after["scheduled_storylet"] is None


# ---------------- 可验证的灵活结果 ----------------

def _force_active(engine, game_id: str, storylet_id: str, scene: str | None = None,
                  facts: dict | None = None, trust: int | None = None,
                  phase: str | None = None):
    state = engine.db.load_state(game_id)
    storylet = engine.content.storylets.get(storylet_id)
    if scene:
        state["scene"] = scene
    if phase:
        state["ending_phase"] = phase
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


def test_allowed_outcomes_are_bound_by_evidence(content):
    from app.rules.storylet_progress import allowed_outcomes
    from app.rules.meaningful_turn import analyze

    storylet = content.storylets.get("late_explanation")
    state = _state(content)
    state["facts"]["misunderstanding_discussed"] = True
    state["storylet_evidence"] = {"quote_raised": True, "quote_discussed": True}
    state["storylet_turns"] = 1

    only_quote = analyze("那句话我听见了。")
    assert allowed_outcomes(state, storylet, only_quote) == {"partially_clarified"}

    explained = analyze("我说的那句话不是在说你，我是说陈屿他们班。")
    state["storylet_evidence"]["explanation_offered"] = True
    assert allowed_outcomes(state, storylet, explained) == {"clarified"}

    state["storylet_evidence"]["pressure"] = True
    assert allowed_outcomes(state, storylet, explained) == {"worse"}


def test_engine_rejects_model_outcome_not_supported_by_evidence(engine, llm_mode, monkeypatch):
    start = engine.start()
    gid = start["game_id"]
    _force_active(engine, gid, "late_explanation", trust=50,
                  facts={"misunderstanding_discussed": True})

    def fake_post(messages):
        return {"choices": [{"message": {"content": json.dumps({
            "dialogue": "……我听着。", "emotion": "guarded", "actions": [],
            "storylet_outcome": "partially_clarified", "npc_intent": None,
        }, ensure_ascii=False)}}], "usage": {"prompt_tokens": 80, "completion_tokens": 10}}

    monkeypatch.setattr(llm_character, "_post", fake_post)
    engine.interact(gid, "我说的那句话不是那个意思，我是说陈屿他们班。", "req_dyn_0000001")

    state = engine.get_state(gid, include_internal=True)["state"]
    resolved = [e for e in engine.get_events(gid)["events"]
                if e["event_id"] == "late_explanation" and e["status"] == "resolved"]
    # 证据足以支撑「澄清」时，模型不能把它降级成「只说开一半」
    assert resolved and resolved[0]["payload"]["outcome"] == "clarified"
    assert state["facts"]["misunderstanding_resolved"] is True


def test_finale_waits_for_a_relationship_signal(engine):
    start = engine.start()
    gid = start["game_id"]
    _force_active(engine, gid, "school_gate_finale", scene="school_gate", phase="prepared")

    engine.interact(gid, "作业写完了吗？", "req_dyn_0000002")
    state = engine.get_state(gid, include_internal=True)["state"]
    assert state["active_storylet"] == "school_gate_finale"
    assert state["ending_id"] is None

    engine.interact(gid, "作业写完了吗？", "req_dyn_0000003")
    state = engine.get_state(gid, include_internal=True)["state"]
    assert state["ending_phase"] == "committed"


def test_walk_home_mutual_talk_marks_shared_walk(engine):
    start = engine.start()
    gid = start["game_id"]
    _force_active(engine, gid, "walk_home", scene="school_gate", trust=50)

    engine.interact(gid, "一起走吧，我也想聊聊分班以后怎么办。", "req_dyn_0000004")
    state = engine.get_state(gid, include_internal=True)["state"]
    assert state["facts"]["walk_home_done"] is True
    resolved = [e for e in engine.get_events(gid)["events"]
                if e["event_id"] == "walk_home" and e["status"] == "resolved"]
    assert resolved[0]["payload"]["outcome"] == "walked_and_talked"


def test_resolution_logs_reason_and_evidence(engine):
    start = engine.start()
    gid = start["game_id"]
    _force_active(engine, gid, "late_explanation", trust=50,
                  facts={"misunderstanding_discussed": True})
    engine.interact(gid, "我说的那句话不是那个意思，我是说陈屿他们班。", "req_dyn_0000005")
    resolved = [e for e in engine.get_events(gid)["events"]
                if e["event_id"] == "late_explanation" and e["status"] == "resolved"][0]
    assert resolved["payload"]["reason"]
    assert isinstance(resolved["payload"]["evidence"], dict)
