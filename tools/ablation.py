"""消融对照：纯 LLM 聊天 / +条件 Storylet / +LLM 导演。

用法：
    python tools/ablation.py --routes communicate --out docs/ABLATION.md
    python tools/ablation.py --routes communicate,avoid

每个组合在独立子进程里跑（环境变量在 import 前生效），互不污染配置。
结果输出 Markdown 表格，可直接放进课程展示材料。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODES = {
    "llm_only": {"ATB_STORYLETS": "0", "ATB_DIRECTOR": "0", "label": "纯 LLM 聊天"},
    "storylet": {"ATB_STORYLETS": "1", "ATB_DIRECTOR": "0", "label": "+ 条件 Storylet"},
    "director": {"ATB_STORYLETS": "1", "ATB_DIRECTOR": "1", "label": "+ LLM 导演"},
}
ROUTE_FILES = {
    "communicate": "ROUTE_COMMUNICATE",
    "control": "ROUTE_CONTROL",
    "avoid": "ROUTE_AVOID",
}


def run_child(mode: str, route: str, max_turns: int) -> dict:
    sys.path.insert(0, str(ROOT / "backend"))
    sys.path.insert(0, str(ROOT / "tests"))

    from app.db import Database
    from app.engine import EndingCommitted, Engine
    import helpers

    texts = getattr(helpers, ROUTE_FILES[route])
    engine = Engine(Database(Path(tempfile.mkdtemp()) / "ablation.db"))
    start = engine.start()
    game_id = start["game_id"]
    ending = None

    for i, text in enumerate(list(texts) + ["嗯。"] * 8):
        if i >= max_turns:
            break
        try:
            data = engine.interact(game_id, text, f"req_abl_{i:04d}")
        except EndingCommitted:
            break
        if data.get("ending"):
            ending = data["ending"]
            break

    state = engine.get_state(game_id, include_internal=True)["state"]
    stats = engine.get_metrics(game_id)
    events = engine.get_events(game_id)["events"]
    storylets = [
        e["event_id"] for e in events
        if e["kind"] == "storylet" and e["status"] == "resolved"
    ]
    return {
        "mode": mode,
        "route": route,
        "ending": (ending or {}).get("id"),
        "title": (ending or {}).get("title"),
        "turns": state["turn_index"],
        "meaningful_turns": state["meaningful_turns"],
        "storylets": storylets,
        "storylet_count": len(storylets),
        "llm_calls": stats["totals"]["calls"],
        "failures": stats["totals"]["failures"],
        "prompt_tokens": stats["totals"]["prompt_tokens"],
        "completion_tokens": stats["totals"]["completion_tokens"],
        "avg_latency_ms": (stats["by_purpose"].get("character", {}) or {}).get("avg_latency_ms", 0),
        "p95_latency_ms": (stats["by_purpose"].get("character", {}) or {}).get("p95_latency_ms", 0),
        "ending_phase": state["ending_phase"],
    }


def build_table(results: list[dict]) -> str:
    lines = [
        "| 模式 | 路线 | 结局 | 回合 | 有效互动 | 触发事件 | LLM 调用 | prompt tokens | 角色均值/P95 (ms) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        ending = r["ending"] or "（未收束）"
        events = "、".join(r["storylets"]) or "—"
        lines.append(
            f"| {MODES[r['mode']]['label']} | {r['route']} | {ending} | {r['turns']} | "
            f"{r['meaningful_turns']} | {events} | {r['llm_calls']} | {r['prompt_tokens']} | "
            f"{r['avg_latency_ms']} / {r['p95_latency_ms']} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="After the Bell 消融对照")
    parser.add_argument("--run", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=sorted(MODES), default="director")
    parser.add_argument("--route", choices=sorted(ROUTE_FILES), default="communicate")
    parser.add_argument("--routes", default="communicate")
    parser.add_argument("--modes", default="llm_only,storylet,director")
    parser.add_argument("--max-turns", type=int, default=24)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    if args.run:
        print(json.dumps(run_child(args.mode, args.route, args.max_turns), ensure_ascii=False))
        return

    routes = [r.strip() for r in args.routes.split(",") if r.strip()]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    results: list[dict] = []

    for mode in modes:
        for route in routes:
            env = dict(os.environ)
            env.update({k: v for k, v in MODES[mode].items() if k.startswith("ATB_")})
            env["PYTHONIOENCODING"] = "utf-8"
            proc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--run",
                 "--mode", mode, "--route", route, "--max-turns", str(args.max_turns)],
                capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(ROOT),
            )
            if proc.returncode != 0:
                print(f"[{mode}/{route}] 失败：{proc.stderr[-800:]}", file=sys.stderr)
                continue
            line = [l for l in proc.stdout.splitlines() if l.strip().startswith("{")][-1]
            results.append(json.loads(line))
            print(f"[{mode}/{route}] done: {results[-1]['ending']}", file=sys.stderr)

    table = build_table(results)
    print(table)
    if args.out:
        out = ROOT / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "# 消融对照（自动生成）\n\n"
            "同一批玩家脚本，在三种配置下各跑一遍。\n\n" + table + "\n",
            encoding="utf-8",
        )
        print(f"\n已写入 {out}")


if __name__ == "__main__":
    main()
