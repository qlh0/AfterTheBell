"""许栀的便签本：记住玩家说过的话，更新后提示，并且不看到别的时间线。"""

from __future__ import annotations

import json

from app import config
from app import game_state as gs
from app import records
from app.agents import prompts
from app.content import load_content
from app.memory import store as memory_store
from app.rules.meaningful_turn import analyze
from app.schemas import DiaryUpdate


def test_filler_is_not_written_down(engine):
    start = engine.start()
    data = engine.interact(start["game_id"], "嗯。", "req_diary_filler1")
    assert data["diary"]["updated"] is False
    assert data["diary"]["entry"] is None
    assert data["diary"]["count"] == 0
    assert data["diary"]["notice"] == ""
    assert engine.get_diary(start["game_id"])["entries"] == []


def test_small_talk_and_confession_are_kept(engine):
    start = engine.start()
    gid = start["game_id"]

    weather = engine.interact(gid, "今天好热。", "req_diary_heat0001")
    assert weather["diary"]["updated"] is True
    assert weather["diary"]["banner"] == "便签本更新了"
    assert weather["diary"]["notice"]
    assert weather["diary"]["entry"]["label"] == "小事"
    assert "热" in weather["diary"]["entry"]["quote"]
    assert weather["diary"]["entry"]["day_label"] == "第一天"
    assert weather["ui_hints"]["diary_notice"] == weather["diary"]["notice"]

    again = engine.interact(gid, "今天好热。", "req_diary_heat0002")
    assert again["diary"]["updated"] is False, "同一句原话不该再写一页"
    assert again["diary"]["count"] == 1

    love = engine.interact(gid, "其实我喜欢你，很久了。", "req_diary_love0001")
    assert love["diary"]["updated"] is True
    assert love["diary"]["entry"]["label"] == "心意"
    assert "喜欢你" in love["diary"]["entry"]["quote"]
    assert love["diary"]["count"] == 2

    blob = json.dumps(love["diary"], ensure_ascii=False)
    for secret in ("affection", "trust", "storylet", "player_expressed", "respect_for"):
        assert secret not in blob
    DiaryUpdate.model_validate(love["diary"])


def test_she_quotes_the_notebook_when_asked(engine, monkeypatch):
    monkeypatch.setattr(config, "STORYLETS_ENABLED", False)
    start = engine.start()
    gid = start["game_id"]

    empty = engine.interact(gid, "你还记得我刚才说过什么吗？", "req_diary_ask00001")
    assert "空" in empty["dialogue"]
    assert empty["diary"]["updated"] is False

    engine.interact(gid, "我有点担心你。", "req_diary_care0001")
    engine.interact(gid, "其实我喜欢你，很久了。", "req_diary_love0002")
    asked = engine.interact(gid, "你还记得我刚才说过什么吗？", "req_diary_ask00002")
    assert "喜欢你" in asked["dialogue"]
    assert "担心" in asked["dialogue"]
    assert asked["diary"]["updated"] is False

    book = engine.get_diary(gid)
    assert [item["label"] for item in book["entries"]] == ["关心", "心意"]
    state = engine.get_state(gid, include_internal=True)["state"]
    assert "_importance" not in state["diary"][0]
    assert "_tags" not in state["diary"][0]


def test_control_and_promise_get_their_own_pages(engine):
    start = engine.start()
    gid = start["game_id"]
    control = engine.interact(gid, "你不许去重点班，听我的。", "req_diary_ctrl0001")
    assert control["diary"]["entry"]["label"] == "决定"
    promise = engine.interact(gid, "我会等你。", "req_diary_prom0001")
    assert promise["diary"]["entry"]["label"] == "承诺"


def test_repeat_request_does_not_write_twice(engine):
    start = engine.start()
    gid = start["game_id"]
    first = engine.interact(gid, "我有点担心你。", "req_diary_idem0001")
    second = engine.interact(gid, "我有点担心你。", "req_diary_idem0001")
    assert first == second
    assert engine.get_diary(gid)["count"] == 1


def test_diary_api_and_unknown_game(client):
    started = client.post("/game/start").json()
    gid = started["game_id"]
    client.post(
        f"/game/{gid}/interact",
        json={"text": "对不起，我刚才说重了。", "request_id": "req_diary_api0001"},
    )
    book = client.get(f"/game/{gid}/diary")
    assert book.status_code == 200
    body = book.json()
    assert body["count"] == 1
    assert body["entries"][0]["label"] == "道歉"
    assert "对不起" in body["entries"][0]["quote"]

    missing = client.get("/game/diary_missing_game/diary")
    assert missing.status_code == 404


def test_restore_hides_future_pages(engine):
    start = engine.start()
    gid = start["game_id"]
    engine.interact(gid, "你最近是不是在躲我？", "req_diary_br000001")
    engine.interact(gid, "其实我喜欢你，很久了。", "req_diary_br000002")

    restored = engine.restore(gid, 1)
    branch = restored["branch_id"]
    book = engine.get_diary(gid)
    assert book["branch_id"] == branch
    assert book["count"] == 1
    assert "躲" in book["entries"][0]["quote"]
    assert all("喜欢你" not in item["quote"] for item in book["entries"])

    recalled = memory_store.recall(engine.db, gid, "喜欢你", k=10, branch_id=branch)
    assert all("喜欢你" not in item["content"] for item in recalled)

    old = memory_store.recall(engine.db, gid, "喜欢你", k=10, branch_id="main")
    assert any("喜欢你" in item["content"] for item in old)


def test_prompt_shows_quotes_without_relationship_numbers():
    content = load_content()
    state = gs.default_state("g_diary", content.goal_ids(), content.budget())
    state["relationship"] = {"affection": 63, "trust": 71, "respect_for_autonomy": 58}
    state["diary"] = [
        {
            "turn": 1,
            "day": 1,
            "day_label": "第一天",
            "scene": "classroom",
            "scene_label": "教室",
            "label": "心意",
            "quote": "其实我喜欢你，很久了。",
            "note": "他忽然把这句说出来了。我抄的时候手有点不稳。",
        }
    ]
    text = prompts.user_prompt(state, analyze("你还好吗？"), None, content, [], [])
    assert "便签本" in text
    assert "其实我喜欢你，很久了。" in text
    for number in ("63", "71", "58"):
        assert number not in text
    system = prompts.system_prompt(content)
    assert "便签" in system


def test_record_includes_the_notebook(engine):
    start = engine.start()
    gid = start["game_id"]
    engine.interact(gid, "其实我喜欢你，很久了。", "req_diary_rec00001")
    state = engine.db.load_state(gid)
    record = records.build_record(
        engine.db,
        state,
        engine.content,
        {"id": "romance", "title": "在一起", "subtitle": "", "epilogue": [], "closing_line": "放学后。"},
    )
    assert record["diary"][0]["label"] == "心意"
    markdown = records.to_markdown(record)
    assert "许栀的便签本" in markdown
    assert "喜欢你" in markdown


def test_long_line_is_trimmed_but_still_recalled(engine):
    start = engine.start()
    gid = start["game_id"]
    text = "我一直想告诉你，" + "很在意你" * 30 + "，这句话很长。"
    data = engine.interact(gid, text, "req_diary_long0001")
    quote = data["diary"]["entry"]["quote"]
    assert quote.endswith("……")
    assert len(quote) < len(text)
    found = memory_store.recall(engine.db, gid, "很在意你", k=6, branch_id="main")
    assert any(item["kind"] == "diary" and "很在意你" in item["content"] for item in found)
