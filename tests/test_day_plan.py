"""轻量「第二天计划」：只影响开场与提示顺序，不改事实/关系/结局。"""

from __future__ import annotations

import pytest

from app.engine import DayPlanNotAvailable, Engine
from app.rules import day_plan


def _state(engine: Engine, gid: str) -> dict:
    return engine.get_state(gid, include_internal=True)["state"]


def _to_day2(engine: Engine) -> tuple[str, dict]:
    start = engine.start()
    gid = start["game_id"]
    engine.advance(gid, "req_plan_day2_000", "continue")
    engine.advance(gid, "req_plan_day2_001", "continue")
    state = _state(engine, gid)
    assert (state["day"], state["scene"]) == (2, "classroom")
    return gid, state


def test_plan_classification():
    assert day_plan.classify("明天想约她去图书馆，把题讲清楚。")[0] == "study"
    assert day_plan.classify("想找她把昨天的话说开。")[0] == "clarify"
    assert day_plan.classify("一起去小卖部买点喝的。")[0] == "snack"
    assert day_plan.classify("我想向她表白。")[0] == "confess"
    assert day_plan.classify("") == ["free"]
    assert len(day_plan.normalize("啊" * 300)) == day_plan.MAX_PLAN_CHARS


def test_plan_requires_day2_classroom(engine):
    start = engine.start()
    with pytest.raises(DayPlanNotAvailable):
        engine.submit_day_plan(start["game_id"], "明天去图书馆。", "req_plan_bad")


def test_plan_affects_only_opening_and_suggestion_order(engine):
    gid, before = _to_day2(engine)
    before_facts = dict(before["facts"])
    before_rel = dict(before["relationship"])

    data = engine.submit_day_plan(
        gid, "明天想约她去图书馆，一起复习数学。", "req_plan_001"
    )
    after = _state(engine, gid)

    assert after["day2_plan"]["status"] == "consumed"
    assert after["day2_plan"]["tags"][0] == "study"
    assert "图书馆" in data["opening"]
    assert after["facts"] == before_facts
    assert after["relationship"] == before_rel
    assert "pending_day_opening" not in after or not after["pending_day_opening"]
    suggestions = data["suggestions"]
    assert suggestions and suggestions[0]["id"] == "library"


def test_plan_cannot_be_submitted_twice(engine):
    gid, _ = _to_day2(engine)
    engine.submit_day_plan(gid, "顺其自然。", "req_plan_002")
    with pytest.raises(DayPlanNotAvailable):
        engine.submit_day_plan(gid, "再去图书馆。", "req_plan_003")


def test_plan_is_idempotent_by_request_id(engine):
    gid, _ = _to_day2(engine)
    first = engine.submit_day_plan(gid, "想找她把话说开。", "req_plan_same")
    second = engine.submit_day_plan(gid, "想找她把话说开。", "req_plan_same")
    assert second["state_version"] == first["state_version"]
    assert second["opening"] == first["opening"]


def test_day_plan_api(client):
    started = client.post("/game/start", json={}).json()
    gid = started["game_id"]
    version = started["state_version"]
    for i in range(2):
        data = client.post(
            f"/game/{gid}/advance",
            json={
                "request_id": f"req_api_plan_{i}",
                "expected_state_version": version,
                "intent": "continue",
            },
        ).json()
        version = data["state_version"]
    response = client.post(
        f"/game/{gid}/day-plan",
        json={
            "text": "明天想约她去图书馆，一起复习数学。",
            "request_id": "req_api_plan_submit",
            "expected_state_version": version,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["day2_plan"]["status"] == "consumed"
    assert body["day2_plan"]["tags"][0] == "study"
