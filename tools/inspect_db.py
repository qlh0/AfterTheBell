"""查看本地 SQLite 里有什么（调试用，不修改数据）。

用法：
    .venv\\Scripts\\python.exe tools\\inspect_db.py
    .venv\\Scripts\\python.exe tools\\inspect_db.py --game demo_xxxxxxxx
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "backend" / "data" / "after_the_bell.db"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--game", default="")
    args = parser.parse_args()

    path = Path(args.db)
    if not path.exists():
        print(f"数据库不存在：{path}")
        return
    print(f"数据库：{path}  （{path.stat().st_size / 1024:.1f} KB）\n")

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    print("表：")
    for table in tables:
        count = conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
        print(f"  - {table:16s} {count:5d} 行 | {', '.join(cols)}")

    rows = conn.execute(
        "SELECT game_id, state_version, updated_at FROM games ORDER BY updated_at DESC LIMIT 5"
    ).fetchall()
    print("\n最近的对局：")
    for r in rows:
        print(f"  {r['game_id']}  v{r['state_version']}  {r['updated_at']}")

    game_id = args.game or (rows[0]["game_id"] if rows else "")
    if not game_id:
        return

    print(f"\n=== 对局 {game_id} ===")
    state = json.loads(conn.execute(
        "SELECT state_json FROM games WHERE game_id=?", (game_id,)).fetchone()["state_json"])
    print(f"分支={state.get('branch_id', 'main')}  场景={state['scene']}  结局阶段={state['ending_phase']}  结局={state['ending_id']}")
    print(f"关系={state['relationship']}")
    print("已成立的事实：" + (", ".join(k for k, v in state["facts"].items() if v) or "无"))
    print(f"目标状态={state['narrative_goals']}")
    print(f"用过的事件={state['used_storylets']}")
    print("线索=" + str([(t.get("id"), t.get("status")) for t in state.get("open_threads", [])]))

    print("\n各表在本局的行数：")
    for table in ("state_snapshots", "requests", "turns", "events", "memories", "llm_calls"):
        count = conn.execute(
            f"SELECT COUNT(*) c FROM {table} WHERE game_id=?", (game_id,)).fetchone()["c"]
        print(f"  - {table:16s} {count}")

    print("\n最近回合：")
    for r in conn.execute(
            "SELECT turn_index, role, substr(text,1,64) t FROM turns WHERE game_id=? ORDER BY id DESC LIMIT 6",
            (game_id,)):
        print(f"  #{r['turn_index']} {r['role']:9s} {r['t']}")

    print("\n最近事件：")
    for r in conn.execute(
            "SELECT event_id, kind, status, state_version FROM events WHERE game_id=? ORDER BY id DESC LIMIT 6",
            (game_id,)):
        print(f"  v{r['state_version']} {r['kind']:8s} {r['status']:9s} {r['event_id']}")

    print("\n最近记忆：")
    for r in conn.execute(
            "SELECT kind, importance, substr(content,1,60) c FROM memories WHERE game_id=? ORDER BY id DESC LIMIT 4",
            (game_id,)):
        print(f"  [{r['kind']}] 重要度{r['importance']} {r['c']}")

    print("\n最近 LLM 调用：")
    for r in conn.execute(
            "SELECT purpose, model, latency_ms, prompt_tokens, completion_tokens, ok, error"
            " FROM llm_calls WHERE game_id=? ORDER BY id DESC LIMIT 4", (game_id,)):
        print(f"  {r['purpose']:9s} {r['model']:14s} {r['latency_ms']}ms  "
              f"in={r['prompt_tokens']} out={r['completion_tokens']} ok={bool(r['ok'])} {r['error']}")


if __name__ == "__main__":
    main()
