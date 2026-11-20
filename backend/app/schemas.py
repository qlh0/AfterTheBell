"""对外 HTTP 契约（Pydantic）。客户端只看到这里定义的字段。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

SCENE_IDS = ("classroom", "school_gate")
SPRITE_IDS = ("xuzhi_normal", "xuzhi_guarded", "xuzhi_smile")
EMOTIONS = ("guarded", "normal", "relieved", "happy", "hurt", "sad", "annoyed", "soft")
ENDING_PHASES = ("none", "eligible", "prepared", "committed")
PLANNING_STATUS = ("not_required", "scheduled", "skipped", "activated", "none")


class Presentation(BaseModel):
    scene_id: str = "classroom"
    sprite_id: str = "xuzhi_guarded"
    event_title: str | None = None
    event_badge: bool = False

    @field_validator("scene_id")
    @classmethod
    def _scene_whitelisted(cls, v: str) -> str:
        if v not in SCENE_IDS:
            raise ValueError(f"scene_id 不在白名单: {v}")
        return v

    @field_validator("sprite_id")
    @classmethod
    def _sprite_whitelisted(cls, v: str) -> str:
        if v not in SPRITE_IDS:
            raise ValueError(f"sprite_id 不在白名单: {v}")
        return v


class Change(BaseModel):
    path: str
    before: Any = None
    after: Any = None
    reason: str = ""


class TurnView(BaseModel):
    index: int = 0
    meaningful_turns: int = 0
    progress: int = 0
    budget: int = 12
    near_end: bool = False


class PublicState(BaseModel):
    scene: str = "classroom"
    ending_phase: str = "none"
    ending_id: str | None = None
    turn: TurnView = Field(default_factory=TurnView)
    can_advance: bool = True
    goals: dict[str, str] = Field(default_factory=dict)


class EndingBlock(BaseModel):
    id: str
    title: str
    subtitle: str = ""
    epilogue: list[str] = Field(default_factory=list)
    closing_line: str = ""


class Suggestion(BaseModel):
    """「可以这么说」提示：只是可编辑的参考句，不是强制选项。"""

    id: str
    label: str
    text: str


class StartRequest(BaseModel):
    player_name: str | None = Field(default=None, max_length=16)


class StartResponse(BaseModel):
    game_id: str
    state_version: int
    narration: list[str] = Field(default_factory=list)
    dialogue: str = ""
    emotion: str = "guarded"
    presentation: Presentation = Field(default_factory=Presentation)
    state: PublicState = Field(default_factory=PublicState)
    suggestions: list[Suggestion] = Field(default_factory=list)


class InteractRequest(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    request_id: str = Field(min_length=8, max_length=64)
    expected_state_version: int | None = None

    @field_validator("text")
    @classmethod
    def _strip_text(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("text 不能为空")
        return v


class AdvanceRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=64)
    expected_state_version: int | None = None
    intent: Literal["continue", "leave_classroom"] = "continue"


class DayPlanRequest(BaseModel):
    text: str = Field(default="", max_length=200)
    request_id: str = Field(min_length=8, max_length=64)
    expected_state_version: int | None = None

    @field_validator("text")
    @classmethod
    def _strip_plan(cls, v: str) -> str:
        return v.strip()


class InteractResponse(BaseModel):
    game_id: str
    request_id: str
    state_version: int
    speaker: str = "xuzhi"
    dialogue: str = ""
    emotion: str = "guarded"
    narration: list[str] = Field(default_factory=list)
    presentation: Presentation = Field(default_factory=Presentation)
    committed_changes: list[Change] = Field(default_factory=list)
    active_event_id: str | None = None
    can_advance: bool = True
    planning_status: str = "not_required"
    scheduled_event_id: str | None = None
    turn: TurnView = Field(default_factory=TurnView)
    state: PublicState = Field(default_factory=PublicState)
    ending: EndingBlock | None = None
    suggestions: list[Suggestion] = Field(default_factory=list)
    ui_hints: dict[str, Any] = Field(default_factory=dict)


class AdvanceResponse(BaseModel):
    game_id: str
    request_id: str
    state_version: int
    narration: list[str] = Field(default_factory=list)
    presentation: Presentation = Field(default_factory=Presentation)
    active_event_id: str | None = None
    can_advance: bool = True
    planning_status: str = "not_required"
    turn: TurnView = Field(default_factory=TurnView)
    state: PublicState = Field(default_factory=PublicState)
    ending: EndingBlock | None = None
    suggestions: list[Suggestion] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: str
    detail: str = ""


class ConflictResponse(BaseModel):
    error: str = "state_version_conflict"
    detail: str = ""
    current_state_version: int
    state: PublicState | None = None
