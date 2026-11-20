"""FastAPI 入口。

契约（M0）：
- 一次 /interact 返回完整 JSON，不做流式；
- request_id 幂等，state_version 乐观并发；
- 后端是唯一权威状态，客户端只拿可展示信息。
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config
from .db import Database
from .engine import (
    DayPlanNotAvailable,
    Engine,
    EndingCommitted,
    GameNotEnded,
    GameNotFound,
    VersionConflict,
)
from .schemas import AdvanceRequest, DayPlanRequest, InteractRequest, StartRequest

API_VERSION = "0.3.2"


def create_app(db: Database | None = None) -> FastAPI:
    config.validate_runtime()
    database = db or Database()
    engine = Engine(database)

    app = FastAPI(
        title="After the Bell API",
        description="《那天放学后》— 自由对话 Galgame 后端（M0：规则闭环 + 模板角色）",
        version=API_VERSION,
    )
    app.state.engine = engine
    app.state.db = database

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:8756",
            "http://localhost:8756",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "api_version": API_VERSION,
            "llm_mode": config.LLM_MODE,
            "llm_configured": config.llm_configured(),
            "llm_model": config.LLM_MODEL if config.LLM_MODE == "llm" else None,
            "storylets": len(engine.content.storylets),
            "goals": len(engine.content.goals),
            "endings": engine.content.ending_order,
            "turn_budget": engine.content.budget(),
        }

    @app.post("/game/start")
    def start_game(body: StartRequest | None = None):
        return engine.start()

    @app.get("/game/{game_id}/state")
    def get_state(game_id: str, include_internal: bool = Query(False, description="仅调试用")):
        return engine.get_state(game_id, include_internal=include_internal)

    @app.post("/game/{game_id}/interact")
    def interact(game_id: str, body: InteractRequest):
        return engine.interact(
            game_id=game_id,
            text=body.text,
            request_id=body.request_id,
            expected_state_version=body.expected_state_version,
        )

    @app.post("/game/{game_id}/advance")
    def advance(game_id: str, body: AdvanceRequest):
        return engine.advance(
            game_id=game_id,
            request_id=body.request_id,
            intent=body.intent,
            expected_state_version=body.expected_state_version,
        )

    @app.post("/game/{game_id}/day-plan")
    def day_plan(game_id: str, body: DayPlanRequest):
        return engine.submit_day_plan(
            game_id=game_id,
            text=body.text,
            request_id=body.request_id,
            expected_state_version=body.expected_state_version,
        )

    @app.get("/game/{game_id}/events")
    def events(game_id: str):
        return engine.get_events(game_id)

    @app.get("/game/{game_id}/metrics")
    def metrics(game_id: str):
        return engine.get_metrics(game_id)

    @app.get("/game/{game_id}/record")
    def game_record(game_id: str, branch_id: str | None = None):
        return engine.get_record(game_id, branch_id)

    @app.get("/records")
    def records(limit: int = Query(30, ge=1, le=200)):
        return engine.list_records(limit)

    @app.post("/game/{game_id}/restore/{version}")
    def restore(game_id: str, version: int):
        return engine.restore(game_id, version)

    @app.get("/games")
    def games(limit: int = Query(20, ge=1, le=100)):
        return {"games": database.list_games(limit)}

    # ---------- 错误映射 ----------

    @app.exception_handler(GameNotFound)
    async def _not_found(_request, exc: GameNotFound):
        return JSONResponse(status_code=404, content={"error": "game_not_found", "detail": str(exc)})

    @app.exception_handler(VersionConflict)
    async def _conflict(_request, exc: VersionConflict):
        return JSONResponse(
            status_code=409,
            content={
                "error": "state_version_conflict",
                "detail": "状态已被更新，请刷新后重试（你的操作没有提交）。",
                "current_state_version": exc.current_version,
            },
        )

    @app.exception_handler(EndingCommitted)
    async def _ended(_request, exc: EndingCommitted):
        return JSONResponse(
            status_code=409,
            content={"error": "ending_committed", "detail": "本局已经结束。", "ending_id": exc.ending_id},
        )

    @app.exception_handler(GameNotEnded)
    async def _not_ended(_request, exc: GameNotEnded):
        return JSONResponse(
            status_code=409,
            content={"error": "game_not_ended", "detail": "本局还没有结束，暂无对局记录。"},
        )

    @app.exception_handler(DayPlanNotAvailable)
    async def _bad_day_plan(_request, exc: DayPlanNotAvailable):
        return JSONResponse(
            status_code=400,
            content={"error": "day_plan_not_available", "detail": str(exc)},
        )

    return app


app = create_app()
