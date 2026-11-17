"""Storylet 库：内容加载 + 合法性过滤。

关键约束：LLM 永远拿不到「全量事件」，只能拿到这里过滤后的合法候选。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .. import game_state as gs
from ..rules import preconditions


@dataclass(frozen=True)
class Storylet:
    id: str
    title: str
    kind: str
    narrative_goal: str
    participants: tuple[str, ...]
    allowed_scenes: tuple[str, ...]
    preconditions: dict[str, Any]
    opening_cue: str
    narrative_hint: str
    possible_outcomes: tuple[str, ...]
    once: bool
    priority: int
    scene_lock: str | None
    exposition: tuple[str, ...] = ()

    def as_prompt_dict(self) -> dict[str, Any]:
        """给导演/角色 prompt 的裁剪版：不含内部判定逻辑。"""
        return {
            "id": self.id,
            "title": self.title,
            "narrative_goal": self.narrative_goal,
            "opening_cue": self.opening_cue,
            "narrative_hint": self.narrative_hint,
            "possible_outcomes": list(self.possible_outcomes),
        }


class StoryletLibrary:
    def __init__(self, storylets: list[Storylet]) -> None:
        self._items = {s.id: s for s in storylets}
        self._order = [s.id for s in storylets]

    @classmethod
    def from_json(cls, doc: dict[str, Any]) -> "StoryletLibrary":
        items: list[Storylet] = []
        seen: set[str] = set()
        for raw in doc.get("storylets", []):
            sid = raw["id"]
            if sid in seen:
                raise ValueError(f"storylet id 重复: {sid}")
            seen.add(sid)
            preconditions.validate(raw["preconditions"], where=f"storylets.{sid}.preconditions")
            for key in ("title", "narrative_goal", "opening_cue", "narrative_hint", "possible_outcomes"):
                if not raw.get(key):
                    raise ValueError(f"storylet {sid} 缺少 {key}")
            items.append(
                Storylet(
                    id=sid,
                    title=raw["title"],
                    kind=raw.get("kind", "generic"),
                    narrative_goal=raw["narrative_goal"],
                    participants=tuple(raw.get("participants", ["player", "xuzhi"])),
                    allowed_scenes=tuple(raw.get("allowed_scenes", gs.SCENES)),
                    preconditions=raw["preconditions"],
                    opening_cue=raw["opening_cue"],
                    narrative_hint=raw["narrative_hint"],
                    possible_outcomes=tuple(raw["possible_outcomes"]),
                    once=bool(raw.get("once", True)),
                    priority=int(raw.get("priority", 50)),
                    scene_lock=raw.get("scene_lock"),
                    exposition=tuple(raw.get("exposition", []) or []),
                )
            )
        if not items:
            raise ValueError("storylets.json 里没有任何事件")
        return cls(items)

    def __len__(self) -> int:
        return len(self._items)

    def all(self) -> list[Storylet]:
        return [self._items[sid] for sid in self._order]

    def get(self, storylet_id: str | None) -> Storylet | None:
        if storylet_id is None:
            return None
        return self._items.get(storylet_id)

    def eligible(self, state: dict[str, Any]) -> list[Storylet]:
        used = set(state.get("used_storylets") or [])
        active = state.get("active_storylet")
        out: list[Storylet] = []
        for storylet in self.all():
            if storylet.once and storylet.id in used:
                continue
            if storylet.id == active:
                continue
            if state["scene"] not in storylet.allowed_scenes:
                continue
            if storylet.scene_lock and state["scene"] != storylet.scene_lock:
                continue
            if not preconditions.evaluate(storylet.preconditions, state):
                continue
            out.append(storylet)
        return out

    def is_still_eligible(self, storylet_id: str, state: dict[str, Any]) -> bool:
        return any(s.id == storylet_id for s in self.eligible(state))
