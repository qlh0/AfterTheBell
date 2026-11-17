"""SQLite 持久化层（标准库 sqlite3，无 ORM）。

表：
- games            当前权威状态（每局一行）
- state_snapshots  每次提交后的完整快照（支持读档/调试）
- requests         request_id → 响应 JSON（重试幂等）
- turns            对话流水
- events           事件/剧情日志（含因果）
- memories         重要记忆（首版规则+关键词检索）
- llm_calls        LLM 调用指标
"""

from __future__ import annotations

import json
import math
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import DB_PATH
from . import game_state as gs

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    game_id        TEXT PRIMARY KEY,
    branch_id      TEXT NOT NULL DEFAULT 'main',
    state_version  INTEGER NOT NULL,
    state_json     TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS state_snapshots (
    game_id     TEXT NOT NULL,
    branch_id   TEXT NOT NULL DEFAULT 'main',
    version     INTEGER NOT NULL,
    state_json  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (game_id, version)
);

CREATE TABLE IF NOT EXISTS requests (
    game_id     TEXT NOT NULL,
    branch_id   TEXT NOT NULL DEFAULT 'main',
    request_id  TEXT NOT NULL,
    endpoint    TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (game_id, branch_id, request_id)
);

CREATE TABLE IF NOT EXISTS turns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id     TEXT NOT NULL,
    branch_id   TEXT NOT NULL DEFAULT 'main',
    turn_index  INTEGER NOT NULL,
    role        TEXT NOT NULL,
    text        TEXT NOT NULL,
    meta_json   TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns_game ON turns(game_id, turn_index);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id     TEXT NOT NULL,
    branch_id   TEXT NOT NULL DEFAULT 'main',
    event_id    TEXT NOT NULL,
    kind        TEXT NOT NULL,
    status      TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    state_version INTEGER NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_game ON events(game_id, id);

CREATE TABLE IF NOT EXISTS memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id     TEXT NOT NULL,
    branch_id   TEXT NOT NULL DEFAULT 'main',
    kind        TEXT NOT NULL,
    content     TEXT NOT NULL,
    importance  INTEGER NOT NULL DEFAULT 3,
    turn_index  INTEGER NOT NULL DEFAULT 0,
    source_event_id TEXT,
    tags_json   TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_game ON memories(game_id, importance DESC);

CREATE TABLE IF NOT EXISTS llm_calls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id     TEXT NOT NULL,
    branch_id   TEXT NOT NULL DEFAULT 'main',
    purpose     TEXT NOT NULL,
    model       TEXT NOT NULL,
    latency_ms  INTEGER NOT NULL DEFAULT 0,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    ok          INTEGER NOT NULL DEFAULT 1,
    error       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS game_records (
    game_id     TEXT NOT NULL,
    branch_id   TEXT NOT NULL,
    ending_id   TEXT,
    created_at  TEXT NOT NULL,
    record_json TEXT NOT NULL,
    PRIMARY KEY (game_id, branch_id)
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | str = DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ---------- 连接与事务 ----------

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        return conn

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """写事务：BEGIN IMMEDIATE 串行化同一数据库的写入，避免状态竞态。"""
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        conn = self.connect()
        try:
            conn.executescript(SCHEMA)
        finally:
            conn.close()
        self._migrate_branch()

    def _migrate_branch(self) -> None:
        """v0.3 迁移：给旧库补 branch_id；requests 主键重建为含分支。

        旧数据统一归到 'main' 分支，可直接继续使用。
        """
        conn = self.connect()
        try:
            for table in ("games", "state_snapshots", "turns", "events", "memories", "llm_calls"):
                cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
                if "branch_id" not in cols:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN branch_id TEXT NOT NULL DEFAULT 'main'")
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(requests)")]
            if "branch_id" not in cols:
                conn.execute("ALTER TABLE requests RENAME TO requests_old")
                conn.execute(
                    "CREATE TABLE requests ("
                    " game_id TEXT NOT NULL, branch_id TEXT NOT NULL DEFAULT 'main',"
                    " request_id TEXT NOT NULL, endpoint TEXT NOT NULL,"
                    " response_json TEXT NOT NULL, created_at TEXT NOT NULL,"
                    " PRIMARY KEY (game_id, branch_id, request_id))"
                )
                conn.execute(
                    "INSERT INTO requests (game_id, branch_id, request_id, endpoint, response_json, created_at)"
                    " SELECT game_id, 'main', request_id, endpoint, response_json, created_at FROM requests_old"
                )
                conn.execute("DROP TABLE requests_old")
        finally:
            conn.close()

    # ---------- 游戏状态 ----------

    def create_game(self, state: dict[str, Any]) -> None:
        now = utcnow()
        branch = state.get("branch_id", "main")
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO games (game_id, branch_id, state_version, state_json, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?)",
                (state["game_id"], branch, state["state_version"], gs.dump_state(state), now, now),
            )
            conn.execute(
                "INSERT INTO state_snapshots (game_id, branch_id, version, state_json, created_at)"
                " VALUES (?,?,?,?,?)",
                (state["game_id"], branch, state["state_version"], gs.dump_state(state), now),
            )

    def load_state(self, game_id: str) -> dict[str, Any] | None:
        with self.read() as conn:
            row = conn.execute("SELECT state_json FROM games WHERE game_id=?", (game_id,)).fetchone()
        if row is None:
            return None
        state = gs.load_state(row["state_json"])
        gs.validate_state(state)
        return state

    def save_state(self, state: dict[str, Any], snapshot: bool = True) -> None:
        gs.validate_state(state)
        now = utcnow()
        payload = gs.dump_state(state)
        branch = state.get("branch_id", "main")
        with self.tx() as conn:
            conn.execute(
                "UPDATE games SET branch_id=?, state_version=?, state_json=?, updated_at=? WHERE game_id=?",
                (branch, state["state_version"], payload, now, state["game_id"]),
            )
            if snapshot:
                conn.execute(
                    "INSERT OR REPLACE INTO state_snapshots (game_id, branch_id, version, state_json, created_at)"
                    " VALUES (?,?,?,?,?)",
                    (state["game_id"], branch, state["state_version"], payload, now),
                )

    def save_state_cas(
        self,
        state: dict[str, Any],
        expected_version: int,
        request_id: str | None = None,
        endpoint: str = "",
        response_payload: dict[str, Any] | None = None,
    ) -> bool:
        """乐观并发提交：只有库里的 version 仍等于 expected_version 才写入。

        状态、快照与幂等响应在同一个事务里提交，避免「画面显示成功、库里没更新」。
        """
        gs.validate_state(state)
        now = utcnow()
        payload = gs.dump_state(state)
        branch = state.get("branch_id", "main")
        with self.tx() as conn:
            cur = conn.execute(
                "UPDATE games SET branch_id=?, state_version=?, state_json=?, updated_at=?"
                " WHERE game_id=? AND state_version=?",
                (branch, state["state_version"], payload, now, state["game_id"], expected_version),
            )
            if cur.rowcount == 0:
                return False
            conn.execute(
                "INSERT OR REPLACE INTO state_snapshots (game_id, branch_id, version, state_json, created_at)"
                " VALUES (?,?,?,?,?)",
                (state["game_id"], branch, state["state_version"], payload, now),
            )
            if request_id and response_payload is not None:
                conn.execute(
                    "INSERT OR REPLACE INTO requests"
                    " (game_id, branch_id, request_id, endpoint, response_json, created_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (
                        state["game_id"],
                        branch,
                        request_id,
                        endpoint,
                        json.dumps(response_payload, ensure_ascii=False),
                        now,
                    ),
                )
        return True

    def load_snapshot(self, game_id: str, version: int) -> dict[str, Any] | None:
        with self.read() as conn:
            row = conn.execute(
                "SELECT state_json FROM state_snapshots WHERE game_id=? AND version=?", (game_id, version)
            ).fetchone()
        return gs.load_state(row["state_json"]) if row else None

    def copy_branch_context(
        self,
        game_id: str,
        from_branch: str,
        to_branch: str,
        max_turn_index: int,
        max_state_version: int,
    ) -> None:
        """读档时把「过去」复制到新分支：只复制读档点之前的对话、记忆与事件。

        新分支因此既有历史上下文，又看不到旧时间线的未来。
        """
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO turns (game_id, branch_id, turn_index, role, text, meta_json, created_at)"
                " SELECT game_id, ?, turn_index, role, text, meta_json, created_at FROM turns"
                " WHERE game_id=? AND branch_id=? AND turn_index<=? ORDER BY id",
                (to_branch, game_id, from_branch, max_turn_index),
            )
            conn.execute(
                "INSERT INTO memories (game_id, branch_id, kind, content, importance, turn_index,"
                " source_event_id, tags_json, created_at)"
                " SELECT game_id, ?, kind, content, importance, turn_index, source_event_id,"
                " tags_json, created_at FROM memories"
                " WHERE game_id=? AND branch_id=? AND turn_index<=? ORDER BY id",
                (to_branch, game_id, from_branch, max_turn_index),
            )
            conn.execute(
                "INSERT INTO events (game_id, branch_id, event_id, kind, status, payload_json,"
                " state_version, created_at)"
                " SELECT game_id, ?, event_id, kind, status, payload_json, state_version, created_at"
                " FROM events WHERE game_id=? AND branch_id=? AND state_version<=? ORDER BY id",
                (to_branch, game_id, from_branch, max_state_version),
            )

    def list_games(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.read() as conn:
            rows = conn.execute(
                "SELECT game_id, branch_id, state_version, updated_at FROM games"
                " ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ---------- 幂等 ----------

    def get_cached_response(
        self, game_id: str, request_id: str, branch_id: str = "main"
    ) -> dict[str, Any] | None:
        with self.read() as conn:
            row = conn.execute(
                "SELECT response_json FROM requests WHERE game_id=? AND branch_id=? AND request_id=?",
                (game_id, branch_id, request_id),
            ).fetchone()
        return json.loads(row["response_json"]) if row else None

    def put_cached_response(
        self, game_id: str, request_id: str, endpoint: str, payload: dict[str, Any],
        branch_id: str = "main",
    ) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO requests"
                " (game_id, branch_id, request_id, endpoint, response_json, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (game_id, branch_id, request_id, endpoint,
                 json.dumps(payload, ensure_ascii=False), utcnow()),
            )

    # ---------- 流水 / 事件 / 记忆 / 指标 ----------

    def add_turn(
        self,
        game_id: str,
        turn_index: int,
        role: str,
        text: str,
        meta: dict[str, Any] | None = None,
        branch_id: str = "main",
    ) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO turns (game_id, branch_id, turn_index, role, text, meta_json, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (game_id, branch_id, turn_index, role, text,
                 json.dumps(meta or {}, ensure_ascii=False), utcnow()),
            )

    def recent_turns(self, game_id: str, limit: int = 8, branch_id: str = "main") -> list[dict[str, Any]]:
        with self.read() as conn:
            rows = conn.execute(
                "SELECT role, text, meta_json, turn_index FROM turns"
                " WHERE game_id=? AND branch_id=? ORDER BY id DESC LIMIT ?",
                (game_id, branch_id, limit),
            ).fetchall()
        out = [{"role": r["role"], "text": r["text"], "turn_index": r["turn_index"]} for r in rows]
        return list(reversed(out))

    def add_event(
        self,
        game_id: str,
        event_id: str,
        kind: str,
        status: str,
        payload: dict[str, Any] | None = None,
        state_version: int = 0,
        branch_id: str = "main",
    ) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO events (game_id, branch_id, event_id, kind, status, payload_json, state_version, created_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (
                    game_id,
                    branch_id,
                    event_id,
                    kind,
                    status,
                    json.dumps(payload or {}, ensure_ascii=False),
                    state_version,
                    utcnow(),
                ),
            )

    def list_events(self, game_id: str, limit: int = 200, branch_id: str = "main") -> list[dict[str, Any]]:
        with self.read() as conn:
            rows = conn.execute(
                "SELECT event_id, kind, status, payload_json, state_version, created_at FROM events"
                " WHERE game_id=? AND branch_id=? ORDER BY id ASC LIMIT ?",
                (game_id, branch_id, limit),
            ).fetchall()
        return [
            {
                "event_id": r["event_id"],
                "kind": r["kind"],
                "status": r["status"],
                "payload": json.loads(r["payload_json"]),
                "state_version": r["state_version"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def add_memory(
        self,
        game_id: str,
        kind: str,
        content: str,
        importance: int = 3,
        turn_index: int = 0,
        source_event_id: str | None = None,
        tags: list[str] | None = None,
        branch_id: str = "main",
    ) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO memories (game_id, branch_id, kind, content, importance, turn_index,"
                " source_event_id, tags_json, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (game_id, branch_id, kind, content, importance, turn_index, source_event_id,
                 json.dumps(tags or [], ensure_ascii=False), utcnow()),
            )

    def all_turns(self, game_id: str, branch_id: str = "main") -> list[dict[str, Any]]:
        """按时间顺序返回某一分支的全部对话流水（生成对局记录用）。"""
        with self.read() as conn:
            rows = conn.execute(
                "SELECT turn_index, role, text, meta_json, created_at FROM turns"
                " WHERE game_id=? AND branch_id=? ORDER BY id ASC",
                (game_id, branch_id),
            ).fetchall()
        return [
            {
                "turn_index": r["turn_index"],
                "role": r["role"],
                "text": r["text"],
                "meta": json.loads(r["meta_json"] or "{}"),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def game_created_at(self, game_id: str) -> str:
        with self.read() as conn:
            row = conn.execute(
                "SELECT created_at FROM games WHERE game_id=?", (game_id,)
            ).fetchone()
        return row["created_at"] if row else ""

    # ---------- 对局记录 ----------

    def save_record(self, game_id: str, branch_id: str, ending_id: str, record: dict[str, Any]) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO game_records"
                " (game_id, branch_id, ending_id, created_at, record_json) VALUES (?,?,?,?,?)",
                (game_id, branch_id, ending_id, utcnow(),
                 json.dumps(record, ensure_ascii=False)),
            )

    def get_record(self, game_id: str, branch_id: str | None = None) -> dict[str, Any] | None:
        with self.read() as conn:
            if branch_id:
                row = conn.execute(
                    "SELECT record_json FROM game_records WHERE game_id=? AND branch_id=?",
                    (game_id, branch_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT record_json FROM game_records WHERE game_id=?"
                    " ORDER BY created_at DESC LIMIT 1",
                    (game_id,),
                ).fetchone()
        return json.loads(row["record_json"]) if row else None

    def list_records(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.read() as conn:
            rows = conn.execute(
                "SELECT game_id, branch_id, ending_id, created_at,"
                " json_extract(record_json, '$.ending.title') AS title,"
                " json_extract(record_json, '$.turns.total') AS turns"
                " FROM game_records ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def add_llm_call(
        self,
        game_id: str,
        purpose: str,
        model: str,
        latency_ms: int,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        ok: bool = True,
        error: str = "",
        branch_id: str = "main",
    ) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO llm_calls (game_id, branch_id, purpose, model, latency_ms,"
                " prompt_tokens, completion_tokens, ok, error, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (game_id, branch_id, purpose, model, latency_ms, prompt_tokens,
                 completion_tokens, 1 if ok else 0, error, utcnow()),
            )

    def llm_metrics(self, game_id: str, branch_id: str | None = None) -> dict[str, Any]:
        where = "game_id=?" + (" AND branch_id=?" if branch_id else "")
        args = (game_id, branch_id) if branch_id else (game_id,)
        with self.read() as conn:
            row = conn.execute(
                "SELECT COUNT(*) n, AVG(latency_ms) avg_ms, SUM(ok=0) fails,"
                f" SUM(prompt_tokens) pt, SUM(completion_tokens) ct FROM llm_calls WHERE {where}",
                args,
            ).fetchone()
        return {
            "calls": row["n"] or 0,
            "avg_latency_ms": round(row["avg_ms"] or 0, 1),
            "failures": row["fails"] or 0,
            "prompt_tokens": row["pt"] or 0,
            "completion_tokens": row["ct"] or 0,
        }

    def llm_stats(self, game_id: str, branch_id: str | None = None) -> dict[str, Any]:
        """分用途的调用统计：调用数、失败数、P50/P95 延迟、token。"""
        where = "game_id=?" + (" AND branch_id=?" if branch_id else "")
        args = (game_id, branch_id) if branch_id else (game_id,)
        with self.read() as conn:
            rows = conn.execute(
                "SELECT purpose, latency_ms, prompt_tokens, completion_tokens, ok, error"
                f" FROM llm_calls WHERE {where} ORDER BY id ASC",
                args,
            ).fetchall()

        def pct(values: list[int], p: float) -> int:
            if not values:
                return 0
            ordered = sorted(values)
            idx = max(0, min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1))
            return ordered[idx]

        by_purpose: dict[str, dict[str, Any]] = {}
        totals = {"calls": 0, "failures": 0, "prompt_tokens": 0, "completion_tokens": 0}
        errors: dict[str, int] = {}
        for row in rows:
            purpose = row["purpose"] or "unknown"
            bucket = by_purpose.setdefault(purpose, {
                "calls": 0, "failures": 0, "latencies": [],
                "prompt_tokens": 0, "completion_tokens": 0, "errors": {},
            })
            bucket["calls"] += 1
            bucket["latencies"].append(int(row["latency_ms"] or 0))
            bucket["prompt_tokens"] += int(row["prompt_tokens"] or 0)
            bucket["completion_tokens"] += int(row["completion_tokens"] or 0)
            totals["calls"] += 1
            totals["prompt_tokens"] += int(row["prompt_tokens"] or 0)
            totals["completion_tokens"] += int(row["completion_tokens"] or 0)
            if not row["ok"]:
                bucket["failures"] += 1
                totals["failures"] += 1
                key = (row["error"] or "unknown").split(":")[0]
                bucket["errors"][key] = bucket["errors"].get(key, 0) + 1
                errors[key] = errors.get(key, 0) + 1

        for bucket in by_purpose.values():
            lat = bucket.pop("latencies")
            bucket["avg_latency_ms"] = round(sum(lat) / len(lat), 1) if lat else 0
            bucket["p50_latency_ms"] = pct(lat, 0.50)
            bucket["p95_latency_ms"] = pct(lat, 0.95)
            bucket["max_latency_ms"] = max(lat) if lat else 0

        return {
            "game_id": game_id,
            "by_purpose": by_purpose,
            "totals": totals,
            "errors": errors,
        }


def new_game_id() -> str:
    return "demo_" + uuid.uuid4().hex[:8]
