"""内容加载：角色、叙事目标、Storylet、结局、节奏参数。

内容一律来自 content/*.json；加载时用前置条件校验器把错误挡在启动阶段。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import CONTENT_DIR, DEFAULT_MEANINGFUL_TURN_BUDGET
from .game_state import FACT_FIELDS
from .narrative.storylets import Storylet, StoryletLibrary
from .rules import preconditions


@dataclass(frozen=True)
class Content:
    characters: dict[str, Any]
    goals: dict[str, Any]
    pacing: dict[str, Any]
    storylets: StoryletLibrary
    endings: dict[str, Any]
    ending_order: list[str]

    def ending(self, ending_id: str) -> dict[str, Any]:
        return self.endings[ending_id]

    def goal_ids(self) -> list[str]:
        return list(self.goals.keys())

    def budget(self) -> int:
        return int(self.pacing.get("default_meaningful_turn_budget", DEFAULT_MEANINGFUL_TURN_BUDGET))


def _read(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_content(content_dir: Path | str = CONTENT_DIR) -> Content:
    root = Path(content_dir)
    chars = _read(root / "characters.json")
    goals_doc = _read(root / "narrative_goals.json")
    story_doc = _read(root / "storylets.json")
    endings_doc = _read(root / "endings.json")

    goals = goals_doc["goals"]
    for gid, spec in goals.items():
        for fact in spec.get("done_when", []):
            name = str(fact)
            if name.startswith("flag:"):
                name = name.split(":", 1)[1]
            if name.startswith("facts."):
                name = name.split(".", 1)[1]
            if name not in FACT_FIELDS:
                raise ValueError(f"narrative_goals.{gid}.done_when 引用了未知事实: {fact}")

    storylets = StoryletLibrary.from_json(story_doc)

    endings = endings_doc["endings"]
    for eid, spec in endings.items():
        preconditions.validate(spec["gates"], where=f"endings.{eid}.gates")
        if not spec.get("title"):
            raise ValueError(f"endings.{eid} 缺少 title")

    order = endings_doc.get("evaluation_order") or list(endings.keys())
    for eid in order:
        if eid not in endings:
            raise ValueError(f"evaluation_order 引用了不存在的结局: {eid}")

    return Content(
        characters=chars["characters"],
        goals=goals,
        pacing=goals_doc.get("pacing", {}),
        storylets=storylets,
        endings=endings,
        ending_order=order,
    )
