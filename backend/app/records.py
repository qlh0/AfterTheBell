"""对局记录：一局结束时把「这一局发生了什么」完整存下来。

三份：
1. SQLite `game_records`（按 game_id + branch_id 唯一）；
2. `backend/data/records/<game>_<branch>.json`（机器可读）；
3. 同目录 `.md`（人可读，含完整对话）。

记录只写一次：结局提交时尽力保存；如果失败或缺失，`GET /game/{id}/record`
会从当前状态与日志重建并补存。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config
from .db import Database

RECORD_VERSION = 1
ROLE_CN = {"player": "你", "xuzhi": "许栀", "narration": "旁白"}


def _parse_time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _duration_seconds(started: str, ended: str) -> int | None:
    start, end = _parse_time(started), _parse_time(ended)
    if not start or not end:
        return None
    return max(0, int((end - start).total_seconds()))


def build_record(
    db: Database,
    state: dict[str, Any],
    content: Any,
    ending_block: dict[str, Any] | None = None,
) -> dict[str, Any]:
    game_id = state["game_id"]
    branch_id = state.get("branch_id", "main")
    turns = db.all_turns(game_id, branch_id)
    events = db.list_events(game_id, limit=2000, branch_id=branch_id)
    stats = db.llm_stats(game_id, branch_id=branch_id)

    ended_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    started_at = turns[0]["created_at"] if turns else db.game_created_at(game_id)

    if ending_block is None and state.get("ending_id"):
        try:
            ending_block = {
                "id": state["ending_id"],
                **{k: v for k, v in content.ending(state["ending_id"]).items()
                   if k in ("title", "subtitle", "epilogue", "closing_line")},
            }
        except Exception:
            ending_block = {"id": state.get("ending_id"), "title": state.get("ending_id")}

    facts = state.get("facts", {})
    threads = []
    for thread in state.get("open_threads", []):
        meta = {}
        try:
            from .rules.threads import THREADS
            meta = THREADS.get(thread["id"], {})
        except Exception:
            pass
        threads.append({
            "id": thread.get("id"),
            "label": meta.get("label", thread.get("id")),
            "status": thread.get("status"),
            "evidence": thread.get("evidence", []),
        })

    resolved = [
        {
            "event_id": e["event_id"],
            "outcome": (e.get("payload", {}).get("outcome")
                        or e.get("payload", {}).get("ending")
                        or e["event_id"]),
            "reason": (e.get("payload", {}).get("reason")
                       or ("最终交流" if e["event_id"] in ("school_gate_finale", "forced_finale") else None)),
        }
        for e in events
        if e["kind"] == "storylet" and e["status"] == "resolved"
    ]
    abandoned = [
        {"event_id": e["event_id"], "reason": e.get("payload", {}).get("reason")}
        for e in events
        if e["kind"] == "storylet" and e["status"] == "abandoned"
    ]

    return {
        "record_version": RECORD_VERSION,
        "game_id": game_id,
        "branch_id": branch_id,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": _duration_seconds(started_at, ended_at),
        "ending": ending_block,
        "turns": {
            "total": state.get("turn_index", 0),
            "meaningful": state.get("meaningful_turns", 0),
            "budget": state.get("budget", {}),
        },
        "relationship": dict(state.get("relationship", {})),
        "facts": dict(facts),
        "facts_true": sorted(k for k, v in facts.items() if v),
        "goals": dict(state.get("narrative_goals", {})),
        "threads": threads,
        "storylets": {
            "used": list(state.get("used_storylets", [])),
            "resolved": resolved,
            "abandoned": abandoned,
        },
        "llm": stats,
        "transcript": [
            {"turn": t["turn_index"], "role": t["role"], "text": t["text"]}
            for t in turns
        ],
    }


def to_markdown(record: dict[str, Any]) -> str:
    ending = record.get("ending") or {}
    lines = [
        "# 《那天放学后》对局记录",
        "",
        f"- 对局：`{record['game_id']}`（分支 `{record['branch_id']}`）",
        f"- 开始：{record.get('started_at', '')}",
        f"- 结束：{record.get('ended_at', '')}",
        f"- 时长：{record.get('duration_seconds') or '—'} 秒",
        f"- 回合：{record['turns']['total']}（有效互动 {record['turns']['meaningful']}）",
        f"- 结局：**{ending.get('title', '—')}**（`{ending.get('id', '—')}`）",
        "",
        "## 最终状态",
        "",
        f"- 关系：{record.get('relationship')}",
        f"- 已成立事实：{', '.join(record.get('facts_true', [])) or '无'}",
        f"- 叙事目标：{record.get('goals')}",
    ]
    if record.get("threads"):
        lines.append("- 线索：")
        for thread in record["threads"]:
            lines.append(f"  - {thread.get('label')}：{thread.get('status')}")
    lines += ["", "## 事件", ""]
    resolved = record.get("storylets", {}).get("resolved", [])
    if resolved:
        for item in resolved:
            lines.append(f"- `{item['event_id']}` → {item.get('outcome')}（{item.get('reason') or '—'}）")
    else:
        lines.append("- 本局没有触发事件。")
    abandoned = record.get("storylets", {}).get("abandoned", [])
    if abandoned:
        lines.append("")
        lines.append("未完成/放弃：")
        for item in abandoned:
            lines.append(f"- `{item['event_id']}`（{item.get('reason') or '—'}）")

    lines += ["", "## 完整对话", ""]
    for item in record.get("transcript", []):
        role = ROLE_CN.get(item["role"], item["role"])
        if item["role"] == "narration":
            lines.append(f"> {item['text']}")
        else:
            lines.append(f"**{role}**：{item['text']}")
        lines.append("")
    lines += [
        "---",
        "",
        f"> {ending.get('closing_line', '')}",
        "",
    ]
    return "\n".join(lines)


def file_stem(record: dict[str, Any]) -> str:
    gid = "".join(c for c in record["game_id"] if c.isalnum() or c in "-_") or "game"
    branch = "".join(c for c in record["branch_id"] if c.isalnum() or c in "-_") or "main"
    return f"{gid}_{branch}"


def save(
    db: Database,
    state: dict[str, Any],
    content: Any,
    ending_block: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = build_record(db, state, content, ending_block)

    directory = Path(config.RECORDS_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    stem = file_stem(record)
    record["files"] = {
        "json": str(directory / f"{stem}.json"),
        "markdown": str(directory / f"{stem}.md"),
    }
    db.save_record(state["game_id"], record["branch_id"], record.get("ending", {}).get("id") or "",
                   record)
    Path(record["files"]["json"]).write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    Path(record["files"]["markdown"]).write_text(to_markdown(record), encoding="utf-8")
    return record
