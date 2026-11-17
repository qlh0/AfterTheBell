"""未解决的剧情线索（open_threads）。

单一事实来源：线索状态**只从已提交的 facts / 关系值推导**，不允许 LLM 直接
声明"问题解决了"。每次同步是幂等的：同样的状态不会重复记 evidence。

三条线索：
- distance_between_us   她为什么疏远你
- misunderstanding_quote 那句被误解的话
- class_change_future   分班之后怎么相处
"""

from __future__ import annotations

from typing import Any

THREADS: dict[str, dict[str, Any]] = {
    "distance_between_us": {
        "label": "她为什么疏远你",
        "open_question": "为什么最近她回消息变慢、放学先走？",
    },
    "misunderstanding_quote": {
        "label": "那句被误解的话",
        "open_question": "她是不是误解了你在走廊说的那句话？",
    },
    "class_change_future": {
        "label": "分班之后怎么相处",
        "open_question": "报了重点班以后，两个人还能像现在这样吗？",
    },
}

TERMINAL = {"resolved", "unresolved", "agreed", "conflicted", "deferred", "worsened"}
ACTIVE_STATUSES = {"open", "discussed", "partially_clarified", "in_progress"}


def ensure(state: dict[str, Any]) -> list[dict[str, Any]]:
    threads = state.setdefault("open_threads", [])
    existing = {t.get("id") for t in threads}
    for tid in THREADS:
        if tid not in existing:
            threads.append({
                "id": tid,
                "status": "open",
                "evidence": [],
                "last_updated_version": 0,
            })
    return threads


def _compute(state: dict[str, Any], thread_id: str) -> tuple[str, str]:
    facts = state["facts"]
    rel = state["relationship"]
    committed = state.get("ending_phase") == "committed"

    if thread_id == "distance_between_us":
        if facts.get("misunderstanding_resolved"):
            return "resolved", "误会解开后，她疏远的原因也说清了"
        if facts.get("player_asked_distance") or facts.get("distance_noticed"):
            if committed:
                return "unresolved", "谈过疏远，但没有真正解决"
            return "discussed", "玩家问起了最近的疏远"
        if committed:
            return "unresolved", "直到结束都没有真正问过"
        return "open", ""

    if thread_id == "misunderstanding_quote":
        if facts.get("misunderstanding_resolved"):
            return "resolved", "那句话被解释清楚，她也信了"
        if facts.get("misunderstanding_discussed"):
            if facts.get("player_controlling"):
                return "worsened", "谈到了那句话，但玩家又替她做了决定"
            if committed:
                return "unresolved", "把话摆上桌了，但没有真正和解"
            return "partially_clarified", "那句话已经进入讨论，但她还没释怀"
        if committed:
            return "unresolved", "那句话始终没有被摊开"
        return "open", ""

    if thread_id == "class_change_future":
        if facts.get("class_change_discussed"):
            if facts.get("player_controlling"):
                return "conflicted", "谈分班时玩家试图替她做决定"
            if rel["respect_for_autonomy"] >= 55:
                if committed:
                    return "agreed", "她的选择被尊重，也说好了以后怎么相处"
                return "discussed", "谈过分班计划和之后的相处"
            if committed:
                return "deferred", "谈过分班，但两个人的以后还没有答案"
            return "discussed", "谈过分班计划"
        if committed:
            return "deferred", "到最后都没有认真谈过分班以后"
        return "open", ""

    return "open", ""


def sync(state: dict[str, Any]) -> list[dict[str, Any]]:
    """把线索状态与事实对齐；状态变化时记录证据。返回变更列表。"""
    threads = ensure(state)
    changes: list[dict[str, Any]] = []
    version = state.get("state_version", 0)

    for thread in threads:
        tid = thread["id"]
        status, reason = _compute(state, tid)
        if status == thread.get("status"):
            continue
        before = thread.get("status")
        thread["status"] = status
        thread["last_updated_version"] = version
        evidence = thread.setdefault("evidence", [])
        evidence.append({
            "version": version,
            "turn": state.get("turn_index", 0),
            "status": status,
            "reason": reason,
        })
        del evidence[:-5]
        changes.append({
            "path": f"open_threads.{tid}.status",
            "before": before,
            "after": status,
            "reason": reason or "thread_update",
        })
    return changes


def active_threads(state: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for thread in ensure(state):
        if thread.get("status") in TERMINAL:
            continue
        out.append({**thread, "label": THREADS[thread["id"]]["label"]})
    return out


def prompt_lines(state: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for thread in ensure(state):
        meta = THREADS[thread["id"]]
        status = thread.get("status", "open")
        lines.append(f"- {meta['label']}（{status}）：{meta['open_question']}")
    return lines


def thread_for_goal(goal_id: str) -> str | None:
    return {
        "notice_distance": "distance_between_us",
        "clarify_misunderstanding": "misunderstanding_quote",
        "discuss_class_change": "class_change_future",
    }.get(goal_id)
