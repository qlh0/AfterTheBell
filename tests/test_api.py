"""HTTP 契约：幂等、版本冲突、错误码、无泄露。"""

from __future__ import annotations

import json
import uuid


def start(client) -> dict:
    resp = client.post("/game/start")
    assert resp.status_code == 200
    return resp.json()


def interact(client, game_id: str, text: str, request_id: str | None = None, version: int | None = None):
    body = {"text": text, "request_id": request_id or ("req_" + uuid.uuid4().hex[:12])}
    if version is not None:
        body["expected_state_version"] = version
    return client.post(f"/game/{game_id}/interact", json=body)


def test_health(client):
    data = client.get("/health").json()
    assert data["ok"] is True
    assert data["storylets"] == 7
    assert data["llm_mode"] == "mock"


def test_start_returns_opening(client):
    data = start(client)
    assert data["game_id"]
    assert data["dialogue"]
    assert data["presentation"]["scene_id"] == "classroom"
    assert data["presentation"]["sprite_id"] in {"xuzhi_normal", "xuzhi_guarded", "xuzhi_smile"}
    assert len(data["narration"]) >= 1


def test_interact_contract(client):
    game_id = start(client)["game_id"]
    resp = interact(client, game_id, "你最近是不是在躲我？")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("game_id", "request_id", "state_version", "speaker", "dialogue",
                "emotion", "presentation", "committed_changes", "active_event_id",
                "can_advance", "planning_status", "turn", "state"):
        assert key in data, key
    assert data["speaker"] == "xuzhi"
    assert data["dialogue"]
    assert data["state_version"] == 1
    assert data["turn"]["index"] == 1


def test_idempotent_request_id(client):
    game_id = start(client)["game_id"]
    req_id = "req_fixed_0001"
    first = interact(client, game_id, "你好。", req_id).json()
    second = interact(client, game_id, "你好。", req_id).json()
    assert first == second
    state = client.get(f"/game/{game_id}/state", params={"include_internal": True}).json()["state"]
    assert state["turn_index"] == 1, "重试不应重复提交玩家行动"


def test_state_version_conflict(client):
    game_id = start(client)["game_id"]
    resp = interact(client, game_id, "你好。", version=999)
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"] == "state_version_conflict"
    assert body["current_state_version"] == 0


def test_unknown_game_404(client):
    resp = interact(client, "demo_does_not_exist", "你好。")
    assert resp.status_code == 404


def test_validation_rejects_empty_text(client):
    game_id = start(client)["game_id"]
    resp = client.post(f"/game/{game_id}/interact", json={"text": "  ", "request_id": "req_x12345678"})
    assert resp.status_code == 422


def test_no_internal_state_leak(client):
    game_id = start(client)["game_id"]
    bodies = [interact(client, game_id, text).json() for text in
              ["你最近是不是在躲我？", "我喜欢你。", "你想报重点班吗？"]]  # noqa: E501
    blob = json.dumps(bodies, ensure_ascii=False)
    for forbidden in ("relationship", "narrative_goals", "misunderstanding_resolved",
                      "personal_goal", "secret", "prompt"):
        assert forbidden not in blob, f"响应泄露了内部字段: {forbidden}"


def test_events_endpoint(client):
    game_id = start(client)["game_id"]
    interact(client, game_id, "你最近是不是在躲我？")
    events = client.get(f"/game/{game_id}/events").json()
    assert events["events"]
    kinds = {e["kind"] for e in events["events"]}
    assert "system" in kinds


def test_ending_committed_rejects_more_turns(client):
    from tests.helpers import ROUTE_CONTROL

    game_id = start(client)["game_id"]
    last = None
    for text in ROUTE_CONTROL:
        resp = interact(client, game_id, text)
        if resp.status_code != 200:
            break
        last = resp.json()
        if last.get("ending"):
            break
    assert last is not None
    assert last["ending"]["id"] == "friends"
    more = interact(client, game_id, "再聊两句。")
    assert more.status_code == 409
    assert more.json()["error"] == "ending_committed"


def test_advance_moves_to_school_gate(client):
    game_id = start(client)["game_id"]
    body = {"request_id": "req_adv_0001", "intent": "leave_classroom"}
    data = client.post(f"/game/{game_id}/advance", json=body).json()
    assert data["state"]["scene"] == "school_gate"
    assert data["narration"]
    assert data["presentation"]["scene_id"] == "school_gate"


def test_restore_snapshot(client):
    game_id = start(client)["game_id"]
    interact(client, game_id, "你最近是不是在躲我？")
    data = client.post(f"/game/{game_id}/restore/0").json()
    assert data["restored_from"] == 0
    state = client.get(f"/game/{game_id}/state", params={"include_internal": True}).json()["state"]
    assert state["turn_index"] == 0
