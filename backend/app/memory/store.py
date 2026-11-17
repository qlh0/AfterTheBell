"""有限长期记忆：结构化写入 + 规则/关键词召回（首版不用向量库）。

存什么：承诺、误会状态、关键经历、冲突。
召回什么：按「与当前输入的关键词重叠」+ 重要度 + 新近度排序，取前 k 条。
"""

from __future__ import annotations

import json
from typing import Any

from ..db import Database


def remember(
    db: Database,
    game_id: str,
    kind: str,
    content: str,
    importance: int = 3,
    turn_index: int = 0,
    source_event_id: str | None = None,
    tags: list[str] | None = None,
    branch_id: str = "main",
) -> None:
    db.add_memory(game_id, kind, content, importance, turn_index, source_event_id,
                  tags or [], branch_id=branch_id)


def _tokens(text: str) -> set[str]:
    """极简中文切分：按标点/空白切，再取 2-3 字片段做重叠匹配。"""
    import re

    clean = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", " ", text)
    chunks = [c for c in clean.split() if c]
    tokens: set[str] = set()
    for chunk in chunks:
        if len(chunk) <= 3:
            tokens.add(chunk)
        else:
            for i in range(len(chunk) - 1):
                tokens.add(chunk[i : i + 2])
    return tokens


def recall(db: Database, game_id: str, query: str, k: int = 6,
           branch_id: str = "main") -> list[dict[str, Any]]:
    """只召回当前时间线（分支）的记忆，读档后不会看到未来。"""
    with db.read() as conn:
        rows = conn.execute(
            "SELECT kind, content, importance, turn_index, tags_json FROM memories"
            " WHERE game_id=? AND branch_id=? ORDER BY importance DESC, id DESC LIMIT 60",
            (game_id, branch_id),
        ).fetchall()
    if not rows:
        return []

    q = _tokens(query)
    scored: list[tuple[float, dict[str, Any]]] = []
    for idx, row in enumerate(rows):
        tags = set(json.loads(row["tags_json"] or "[]"))
        content = row["content"]
        overlap = len(q & _tokens(content))
        tag_hit = len(q & tags)
        # 重要度 > 新近度 > 关键词重叠
        score = overlap * 2.0 + tag_hit * 2.5 + row["importance"] * 0.8 - idx * 0.15
        scored.append(
            (
                score,
                {
                    "kind": row["kind"],
                    "content": content,
                    "importance": row["importance"],
                    "turn_index": row["turn_index"],
                    "tags": sorted(tags),
                },
            )
        )
    scored.sort(key=lambda x: -x[0])
    return [item for score, item in scored[:k] if score > 0]


def format_for_prompt(memories: list[dict[str, Any]]) -> str:
    if not memories:
        return "（暂无重要记忆）"
    lines = []
    for m in memories:
        lines.append(f"- [{m['kind']}] {m['content']}")
    return "\n".join(lines)
