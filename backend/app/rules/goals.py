"""叙事目标推进：由 content/narrative_goals.json 的谓词驱动。

v0.3：不再在 Python 里硬编码一套目标条件——JSON 里的 `progress_if` / `done_if`
是唯一判定来源，避免"文档写一套、代码判一套"。
"""

from __future__ import annotations

from typing import Any

from ..rules import preconditions

ORDER = {"skipped": 0, "pending": 1, "in_progress": 2, "done": 3, "failed": 4}


def record_goal_progress(state: dict[str, Any], content: Any) -> list[dict[str, Any]]:
    goals = state["narrative_goals"]
    changes: list[dict[str, Any]] = []

    def advance(goal_id: str, status: str) -> None:
        before = goals.get(goal_id, "pending")
        if ORDER.get(status, 0) <= ORDER.get(before, 0):
            return
        goals[goal_id] = status
        changes.append({
            "path": f"narrative_goals.{goal_id}",
            "before": before,
            "after": status,
            "reason": "goal_progress",
        })

    for goal_id, spec in content.goals.items():
        if goal_id not in goals:
            goals[goal_id] = "pending"
        status = goals[goal_id]
        if status in ("done", "failed"):
            continue

        optional = bool(spec.get("optional"))
        activate_if = spec.get("activate_if")
        if optional:
            if status == "skipped":
                if activate_if and preconditions.evaluate(activate_if, state):
                    advance(goal_id, "pending")
                continue
            if not (activate_if and preconditions.evaluate(activate_if, state)):
                goals[goal_id] = "skipped"
                changes.append({
                    "path": f"narrative_goals.{goal_id}",
                    "before": status,
                    "after": "skipped",
                    "reason": "optional_goal_skipped",
                })
                continue

        done_if = spec.get("done_if")
        progress_if = spec.get("progress_if")
        if done_if and preconditions.evaluate(done_if, state):
            advance(goal_id, "done")
        elif progress_if and preconditions.evaluate(progress_if, state):
            advance(goal_id, "in_progress")

    return changes
