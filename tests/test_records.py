"""对局记录：结局时保存，可查询、可重建，且只存一份。"""

from __future__ import annotations

import json

from app import config
from app import game_state as gs
from app.rules import threads
from tests.helpers import ROUTE_COMMUNICATE, play


def _play_to_end(engine):
    game_id, last, history = play(engine, ROUTE_COMMUNICATE)
    assert last.get("ending") is not None
    return game_id, last


def test_record_saved_on_ending(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RECORDS_DIR", tmp_path / "records")
    game_id, last = _play_to_end(engine)

    record = engine.get_record(game_id)
    assert record["record_version"] == 1
    assert record["game_id"] == game_id
    assert record["ending"]["id"] == last["ending"]["id"]
    assert record["turns"]["total"] >= 8
    assert record["turns"]["meaningful"] >= 6
    assert record["relationship"]["trust"] > 0
    assert "misunderstanding_discussed" in record["facts_true"] or record["facts"] is not None
    assert record["transcript"], "记录里应包含完整对话"
    assert record["transcript"][0]["role"] == "narration"
    assert any(item["role"] == "player" for item in record["transcript"])
    assert record["llm"]["totals"]["calls"] >= 0
    assert record["threads"], "记录里应包含线索状态"

    files = record["files"]
    assert (tmp_path / "records").exists()
    on_disk = json.loads(open(files["json"], encoding="utf-8").read())
    assert on_disk["ending"]["id"] == last["ending"]["id"]
    markdown = open(files["markdown"], encoding="utf-8").read()
    assert "对局记录" in markdown
    assert "完整对话" in markdown


def test_record_is_saved_once(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RECORDS_DIR", tmp_path / "records")
    game_id, _ = _play_to_end(engine)
    engine.get_record(game_id)
    engine.get_record(game_id)
    rows = engine.db.list_records(50)
    assert len([r for r in rows if r["game_id"] == game_id]) == 1


def test_record_rebuilds_if_missing(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RECORDS_DIR", tmp_path / "records")
    game_id, _ = _play_to_end(engine)
    with engine.db.tx() as conn:
        conn.execute("DELETE FROM game_records WHERE game_id=?", (game_id,))
    rebuilt = engine.get_record(game_id)
    assert rebuilt["ending"]["id"]


def test_record_not_available_before_ending(engine):
    import pytest
    from app.engine import GameNotEnded

    start = engine.start()
    with pytest.raises(GameNotEnded):
        engine.get_record(start["game_id"])


def test_record_api(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RECORDS_DIR", tmp_path / "records")
    game_id = client.post("/game/start").json()["game_id"]
    early = client.get(f"/game/{game_id}/record")
    assert early.status_code == 409
    assert early.json()["error"] == "game_not_ended"

    for i, text in enumerate(ROUTE_COMMUNICATE):
        resp = client.post(f"/game/{game_id}/interact",
                           json={"text": text, "request_id": f"req_rec_{i:06d}"})
        assert resp.status_code == 200
        if resp.json().get("ending"):
            break

    record = client.get(f"/game/{game_id}/record")
    assert record.status_code == 200
    body = record.json()
    assert body["ending"]["id"] in {"romance", "friends", "missed"}

    listing = client.get("/records").json()["records"]
    assert any(item["game_id"] == game_id for item in listing)
