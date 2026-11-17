"""P0-3：读档必须切到新时间线，不能看到"未来"的记忆与对话。"""

from __future__ import annotations

import sqlite3

from app.db import Database
from app.memory import store as memory_store


def _turns_text(db, gid, branch):
    return " ".join(t["text"] for t in db.recent_turns(gid, limit=100, branch_id=branch))


def test_restore_isolates_future_memories(engine):
    start = engine.start()
    gid = start["game_id"]
    engine.interact(gid, "你最近是不是在躲我？", "req_tl_00000001")          # v1
    engine.interact(gid, "分班的事你想好了吗？分班以后还能一起走吗？", "req_tl_00000002")  # v2

    res = engine.restore(gid, 1)
    new_branch = res["branch_id"]
    state = engine.get_state(gid, include_internal=True)["state"]
    assert state["branch_id"] == new_branch
    assert state["state_version"] == 3

    new_turns = _turns_text(engine.db, gid, new_branch)
    assert "躲我" in new_turns
    assert "还能一起走吗" not in new_turns, "新时间线不能看到读档点之后的对话"

    memories = memory_store.recall(engine.db, gid, "还能一起走吗", k=10, branch_id=new_branch)
    assert all("还能一起走吗" not in m["content"] for m in memories)

    # 旧时间线数据仍在（审计/回溯用），只是当前分支看不到
    old_turns = _turns_text(engine.db, gid, "main")
    assert "还能一起走吗" in old_turns

    events = engine.get_events(gid)["events"]
    assert all("还能一起走吗" not in str(e.get("payload", "")) for e in events)


def test_new_branch_continues_and_old_branch_untouched(engine):
    start = engine.start()
    gid = start["game_id"]
    engine.interact(gid, "你最近是不是在躲我？", "req_tl_00000003")
    engine.interact(gid, "分班的事你想好了吗？分班以后还能一起走吗？", "req_tl_00000004")

    res = engine.restore(gid, 1)
    new_branch = res["branch_id"]

    data = engine.interact(gid, "我那天真的不是在说你。", "req_tl_00000005")
    assert data["state_version"] == 4
    state = engine.get_state(gid, include_internal=True)["state"]
    assert state["branch_id"] == new_branch
    assert state["turn_index"] == 2  # 从读档点继续

    with engine.db.read() as conn:
        main_turns = conn.execute(
            "SELECT COUNT(*) c FROM turns WHERE game_id=? AND branch_id='main'", (gid,)
        ).fetchone()["c"]
        new_turns = conn.execute(
            "SELECT COUNT(*) c FROM turns WHERE game_id=? AND branch_id=?", (gid, new_branch)
        ).fetchone()["c"]
    assert main_turns > 0 and new_turns > 0


def test_restore_clears_active_and_scheduled_storylets(engine):
    start = engine.start()
    gid = start["game_id"]
    engine.interact(gid, "你最近是不是在躲我？", "req_tl_00000006")

    state = engine.db.load_state(gid)
    state["scheduled_storylet"] = "walk_home"
    state["active_storylet"] = "old_note"
    state["storylet_stage"] = "active"
    state["storylet_evidence"] = {"engaged": True}
    state["state_version"] += 1
    engine.db.save_state(state)
    version = state["state_version"]

    res = engine.restore(gid, version)
    restored = engine.get_state(gid, include_internal=True)["state"]
    assert restored["branch_id"] == res["branch_id"]
    assert restored["active_storylet"] is None
    assert restored["scheduled_storylet"] is None
    assert restored["storylet_stage"] == "none"
    assert restored["last_plan_turn"] == -1


def test_same_request_id_on_new_branch_is_not_old_cache(engine):
    start = engine.start()
    gid = start["game_id"]
    engine.interact(gid, "你最近是不是在躲我？", "req_tl_00000007")
    old = engine.interact(gid, "分班的事你想好了吗？", "req_tl_00000008")

    engine.restore(gid, 1)
    fresh = engine.interact(gid, "分班的事你想好了吗？", "req_tl_00000008")
    assert fresh["state_version"] != old["state_version"]
    assert fresh["request_id"] == "req_tl_00000008"


def test_legacy_database_gets_migrated(tmp_path):
    """旧库（没有 branch_id）打开后应自动迁移，数据归到 main 分支。"""
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE games (game_id TEXT PRIMARY KEY, state_version INTEGER NOT NULL,
            state_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE state_snapshots (game_id TEXT NOT NULL, version INTEGER NOT NULL,
            state_json TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (game_id, version));
        CREATE TABLE requests (game_id TEXT NOT NULL, request_id TEXT NOT NULL,
            endpoint TEXT NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY (game_id, request_id));
        CREATE TABLE turns (id INTEGER PRIMARY KEY AUTOINCREMENT, game_id TEXT NOT NULL,
            turn_index INTEGER NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL,
            meta_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
        CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, game_id TEXT NOT NULL,
            event_id TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}', state_version INTEGER NOT NULL,
            created_at TEXT NOT NULL);
        CREATE TABLE memories (id INTEGER PRIMARY KEY AUTOINCREMENT, game_id TEXT NOT NULL,
            kind TEXT NOT NULL, content TEXT NOT NULL, importance INTEGER NOT NULL DEFAULT 3,
            turn_index INTEGER NOT NULL DEFAULT 0, source_event_id TEXT,
            tags_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL);
        CREATE TABLE llm_calls (id INTEGER PRIMARY KEY AUTOINCREMENT, game_id TEXT NOT NULL,
            purpose TEXT NOT NULL, model TEXT NOT NULL, latency_ms INTEGER NOT NULL DEFAULT 0,
            prompt_tokens INTEGER NOT NULL DEFAULT 0, completion_tokens INTEGER NOT NULL DEFAULT 0,
            ok INTEGER NOT NULL DEFAULT 1, error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
        """
    )
    conn.execute(
        "INSERT INTO turns (game_id, turn_index, role, text, created_at)"
        " VALUES ('demo_old', 0, 'player', '旧数据', 'x')"
    )
    conn.commit()
    conn.close()

    db = Database(path)
    with db.read() as conn:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(turns)")]
        assert "branch_id" in cols
        row = conn.execute("SELECT branch_id FROM turns WHERE game_id='demo_old'").fetchone()
        assert row["branch_id"] == "main"
        req_cols = [r["name"] for r in conn.execute("PRAGMA table_info(requests)")]
        assert "branch_id" in req_cols
