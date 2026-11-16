"""游戏引擎：把「玩家输入 → 角色对白 → 规则提交 → 事件/结局」串成一次完整回合。

一次 /interact 的固定顺序（普通对话只调用一次角色 Agent，不串行调导演）：
    读状态 → 激活已排期事件 → 解析输入 → 角色回复（1 次 Agent）
    → 白名单动作提交 → 事件收尾 → 回合计数 → 场景推进
    → 目标/结局资格 → （必要时）确定性规划下一事件 → 乐观并发提交 → 返回完整 JSON
"""

from __future__ import annotations

from typing import Any

from . import game_state as gs
from .agents import character
from .agents.mock_character import AgentReply
from .content import Content, load_content
from .db import Database, new_game_id
from .memory import store as memory_store
from .narrative import scheduler
from .rules import actions as action_rules
from .rules import endings as ending_rules
from .rules import meaningful_turn, storylet_resolution

OPENING_NARRATION = [
    "放学铃响过二十分钟，教室里只剩下你们两个。",
    "窗外的操场已经空了，最后一排的椅子被值日生摞在墙角。",
    "她把桌上那张对折的纸往课本下面推了推，抬头看你。",
]
OPENING_LINE = "「你怎么还在？」"


class GameNotFound(Exception):
    pass


class VersionConflict(Exception):
    def __init__(self, current_version: int, state: dict[str, Any]) -> None:
        super().__init__(f"state_version 冲突：当前 {current_version}")
        self.current_version = current_version
        self.state = state


class EndingCommitted(Exception):
    def __init__(self, ending_id: str | None) -> None:
        super().__init__(f"本局已结束：{ending_id}")
        self.ending_id = ending_id


class Engine:
    def __init__(self, db: Database, content: Content | None = None) -> None:
        self.db = db
        self.content = content or load_content()

    # ---------------- 对外：开始 ----------------

    def start(self) -> dict[str, Any]:
        game_id = new_game_id()
        state = gs.default_state(game_id, self.content.goal_ids(), self.content.budget())
        state["npc"]["current_emotion"] = gs.derive_emotion(state)
        self.db.create_game(state)
        self.db.add_event(game_id, "game_started", "system", "committed", {"scene": state["scene"]}, 0)
        for line in OPENING_NARRATION:
            self.db.add_turn(game_id, 0, "narration", line)
        self.db.add_turn(game_id, 0, "xuzhi", OPENING_LINE, {"opening": True})
        return {
            "game_id": game_id,
            "state_version": state["state_version"],
            "narration": list(OPENING_NARRATION),
            "dialogue": OPENING_LINE,
            "emotion": "guarded",
            "presentation": self._presentation(state),
            "state": self._public_state(state),
        }

    # ---------------- 对外：一次对话 ----------------

    def interact(
        self,
        game_id: str,
        text: str,
        request_id: str,
        expected_state_version: int | None = None,
    ) -> dict[str, Any]:
        cached = self.db.get_cached_response(game_id, request_id)
        if cached is not None:
            return cached

        state = self.db.load_state(game_id)
        if state is None:
            raise GameNotFound(game_id)
        if state["ending_phase"] == "committed":
            raise EndingCommitted(state.get("ending_id"))
        if expected_state_version is not None and expected_state_version != state["state_version"]:
            raise VersionConflict(state["state_version"], state)

        base_version = state["state_version"]
        changes: list[dict[str, Any]] = []
        narration: list[str] = []
        events: list[dict[str, Any]] = []
        memories: list[dict[str, Any]] = []

        # 1. 新回合开始：激活已排期事件（或直接进入 finale）
        activation = scheduler.try_activate(state, self.content.storylets)
        if activation is not None:
            narration.append(activation.cue)
            changes.append({
                "path": "active_storylet",
                "before": None,
                "after": activation.storylet.id,
                "reason": f"activated:{activation.how}",
            })
            events.append({
                "event_id": activation.storylet.id,
                "kind": "storylet",
                "status": "activated",
                "payload": {"how": activation.how, "title": activation.storylet.title},
            })

        active = self.content.storylets.get(state["active_storylet"])

        # 2. 解析玩家输入（规则，不依赖模型）
        analysis = meaningful_turn.analyze(text)

        # 3. 角色回复：普通对话只在这里调用一次 Agent
        expected_ending = None
        if active is not None and active.kind == "finale":
            expected_ending = ending_rules.preview_ending(state, self.content)
        reply = character.reply(
            state, analysis, active, expected_ending, db=self.db, game_id=game_id
        )
        self._record_llm(game_id, reply)
        if getattr(reply, "beat", None):
            narration.append(reply.beat)

        # 4. 提交动作（白名单 + 每回合上限）
        #    玩家意图以规则解析为准；模型的动作提议只作记录，不能替玩家表态。
        action_changes, notes = action_rules.commit_actions(
            state, analysis.actions, reason=f"turn:{state['turn_index']}"
        )
        if reply.actions and set(reply.actions) != set(analysis.actions):
            notes.append("llm_actions:" + ",".join(sorted(reply.actions)))
        if reply.notes:
            notes.extend(reply.notes)
        changes.extend(action_changes)

        # 5. 事件收尾：结果依据本回合实际互动
        ending_block: dict[str, Any] | None = None
        resolved_id: str | None = None
        if active is not None:
            started = state.get("storylet_started_turn") or state["turn_index"]
            if active.kind == "finale":
                if analysis.is_meaningful or (state["turn_index"] + 1) >= int(state["budget"]["hard_end_at"]):
                    resolution = ending_rules.resolve(state, self.content)
                    changes.extend(resolution.changes)
                    ending_block = ending_rules.ending_block(state, self.content)
                    resolved_id = active.id
                    events.append({
                        "event_id": active.id,
                        "kind": "storylet",
                        "status": "resolved",
                        "payload": {"ending": state["ending_id"], "failed_goals": resolution.failed_goals},
                    })
                    memories.append({
                        "kind": "ending",
                        "content": f"结局：{ending_block['title']}",
                        "importance": 5,
                        "tags": ["ending", state.get("ending_id") or ""],
                    })
            elif analysis.is_meaningful or (state["turn_index"] - started) >= 2:
                resolution = storylet_resolution.resolve(
                    state, active, analysis, reply.storylet_outcome
                )
                if resolution is not None:
                    changes.extend(resolution.changes)
                    narration.extend(resolution.narration)
                    scheduler.clear_active(state)
                    resolved_id = active.id
                    events.append({
                        "event_id": active.id,
                        "kind": "storylet",
                        "status": "resolved",
                        "payload": {
                            "outcome": resolution.outcome,
                            "proposed_outcome": reply.storylet_outcome,
                        },
                    })
                    if resolution.memory is not None:
                        kind, content, importance, tags = resolution.memory
                        memories.append({
                            "kind": kind,
                            "content": content,
                            "importance": importance,
                            "tags": tags,
                        })

        # 6. 回合计数
        state["turn_index"] += 1
        if analysis.is_meaningful:
            state["meaningful_turns"] += 1

        # 7. 场景推进：放学了就该走，避免玩家永远困在教室
        if state["scene"] == "classroom" and (
            "leave" in analysis.topics or gs.progress(state) >= 5
        ):
            state["scene"] = "school_gate"
            narration.append("你们收好各自的东西，一前一后下了楼。校门口的路灯刚亮。")
            changes.append({
                "path": "scene",
                "before": "classroom",
                "after": "school_gate",
                "reason": "after_school",
            })
            events.append({"event_id": "scene_transition", "kind": "scene", "status": "committed",
                           "payload": {"to": "school_gate"}})

        # 8. 目标与结局资格
        changes.extend(action_rules.record_goal_progress(state))
        if ending_rules.maybe_make_eligible(state):
            changes.append({
                "path": "ending_phase",
                "before": "none",
                "after": "eligible",
                "reason": "finale_reachable",
            })
            events.append({"event_id": "ending_eligible", "kind": "ending", "status": "eligible",
                           "payload": {}})

        # 9. 规划下一事件（确定性，不调用 LLM；失败/过时都不影响本回合对白）
        planning_status = "not_required"
        if state["ending_phase"] != "committed":
            reason = (
                "storylet_resolved" if resolved_id
                else ("fact_unlocked" if action_changes else "turn")
            )
            plan = scheduler.plan_next(state, self.content.storylets, reason)
            planning_status = plan.status
            if plan.status == "scheduled" and plan.storylet_id:
                events.append({
                    "event_id": plan.storylet_id,
                    "kind": "storylet",
                    "status": "scheduled",
                    "payload": {"reason": plan.reason, "based_on_version": state["state_version"]},
                })

        # 10. 收尾：情绪 → 版本 → 乐观并发提交 → 日志
        emotion = reply.emotion if reply.emotion in gs.EMOTIONS else gs.derive_emotion(state)
        if state["relationship"]["respect_for_autonomy"] < 35 or state["ending_phase"] == "committed":
            emotion = gs.derive_emotion(state)
        state["npc"]["current_emotion"] = emotion
        state["state_version"] = base_version + 1
        current_active = self.content.storylets.get(state["active_storylet"])

        response = self._interact_response(
            state=state,
            request_id=request_id,
            reply=reply,
            analysis=analysis,
            narration=narration,
            changes=changes,
            planning_status=planning_status,
            storylet=current_active,
            ending_block=ending_block,
            notes=notes,
        )

        if not self.db.save_state_cas(state, base_version, request_id, "interact", response):
            latest = self.db.load_state(game_id) or state
            raise VersionConflict(latest.get("state_version", -1), latest)

        self._persist_turn_logs(game_id, state, text, reply, analysis, narration, events, memories)
        return response

    # ---------------- 对外：推进/离场 ----------------

    def advance(
        self,
        game_id: str,
        request_id: str,
        intent: str = "continue",
        expected_state_version: int | None = None,
    ) -> dict[str, Any]:
        cached = self.db.get_cached_response(game_id, request_id)
        if cached is not None:
            return cached

        state = self.db.load_state(game_id)
        if state is None:
            raise GameNotFound(game_id)
        if state["ending_phase"] == "committed":
            raise EndingCommitted(state.get("ending_id"))
        if expected_state_version is not None and expected_state_version != state["state_version"]:
            raise VersionConflict(state["state_version"], state)

        base_version = state["state_version"]
        narration: list[str] = []
        changes: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []

        if state["scene"] == "classroom" or intent == "leave_classroom":
            if state["scene"] != "school_gate":
                state["scene"] = "school_gate"
                narration.append("你们收好各自的东西，一前一后下了楼。校门口的路灯刚亮。")
                changes.append({"path": "scene", "before": "classroom", "after": "school_gate",
                                "reason": "player_advance"})

        activation = scheduler.try_activate(state, self.content.storylets)
        planning_status = "not_required"
        if activation is not None:
            narration.append(activation.cue)
            changes.append({"path": "active_storylet", "before": None,
                            "after": activation.storylet.id, "reason": f"activated:{activation.how}"})
            events.append({"event_id": activation.storylet.id, "kind": "storylet",
                           "status": "activated", "payload": {"how": activation.how}})
            planning_status = "activated"
        else:
            plan = scheduler.plan_next(state, self.content.storylets, "advance")
            planning_status = plan.status
            if plan.status == "scheduled" and plan.storylet_id:
                events.append({"event_id": plan.storylet_id, "kind": "storylet", "status": "scheduled",
                               "payload": {"reason": plan.reason}})

        changes.extend(action_rules.record_goal_progress(state))
        if ending_rules.maybe_make_eligible(state):
            changes.append({"path": "ending_phase", "before": "none", "after": "eligible",
                            "reason": "finale_reachable"})

        state["npc"]["current_emotion"] = gs.derive_emotion(state)
        state["state_version"] = base_version + 1
        active = self.content.storylets.get(state["active_storylet"])
        response = {
            "game_id": game_id,
            "request_id": request_id,
            "state_version": state["state_version"],
            "narration": narration,
            "presentation": self._presentation(state),
            "active_event_id": state["active_storylet"],
            "can_advance": True,
            "planning_status": planning_status,
            "turn": self._turn_view(state),
            "state": self._public_state(state),
            "ending": None,
        }
        response["presentation"]["event_title"] = active.title if active else None
        response["presentation"]["event_badge"] = active is not None

        if not self.db.save_state_cas(state, base_version, request_id, "advance", response):
            latest = self.db.load_state(game_id) or state
            raise VersionConflict(latest.get("state_version", -1), latest)

        self.db.add_turn(game_id, state["turn_index"], "narration", "\n".join(narration) or "（你们站了一会儿。）")
        for ev in events:
            self.db.add_event(game_id, ev["event_id"], ev["kind"], ev["status"], ev["payload"],
                              state["state_version"])
        return response

    # ---------------- 对外：读取 ----------------

    def get_state(self, game_id: str, include_internal: bool = False) -> dict[str, Any]:
        state = self.db.load_state(game_id)
        if state is None:
            raise GameNotFound(game_id)
        payload = {
            "game_id": game_id,
            "authoritative": True,
            "state_version": state["state_version"],
        }
        if include_internal:
            payload["state"] = state
        else:
            payload["state"] = self._public_state(state)
        return payload

    def get_events(self, game_id: str) -> dict[str, Any]:
        state = self.db.load_state(game_id)
        if state is None:
            raise GameNotFound(game_id)
        return {"game_id": game_id, "events": self.db.list_events(game_id),
                "metrics": self.db.llm_metrics(game_id)}

    def restore(self, game_id: str, version: int) -> dict[str, Any]:
        """读档：把服务端快照恢复成新的最新版本（历史不丢）。"""
        snapshot = self.db.load_snapshot(game_id, version)
        if snapshot is None:
            raise GameNotFound(f"{game_id}@v{version}")
        current = self.db.load_state(game_id)
        if current is None:
            raise GameNotFound(game_id)
        base_version = current["state_version"]
        snapshot["state_version"] = base_version + 1
        if not self.db.save_state_cas(snapshot, base_version):
            latest = self.db.load_state(game_id) or snapshot
            raise VersionConflict(latest.get("state_version", -1), latest)
        self.db.add_event(game_id, "restore", "system", "committed",
                          {"restored_version": version}, snapshot["state_version"])
        return {"restored_from": version, "state_version": snapshot["state_version"],
                "state": self._public_state(snapshot)}

    # ---------------- 内部 ----------------

    def _record_llm(self, game_id: str, reply: AgentReply) -> None:
        """把这次角色调用的指标落库；mock 路径没有 model，直接跳过。"""
        if not reply.model:
            return
        self.db.add_llm_call(
            game_id=game_id,
            purpose="character",
            model=reply.model,
            latency_ms=reply.latency_ms,
            prompt_tokens=reply.prompt_tokens,
            completion_tokens=reply.completion_tokens,
            ok=reply.source == "llm",
            error=reply.error,
        )

    def _turn_view(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "index": state["turn_index"],
            "meaningful_turns": state["meaningful_turns"],
            "progress": gs.progress(state),
            "budget": int(state["budget"]["max_meaningful_turns"]),
            "near_end": gs.near_end(state),
        }

    def _public_state(self, state: dict[str, Any]) -> dict[str, Any]:
        # goals 属于系统信息，默认不下发给玩家可见层
        return {
            "scene": state["scene"],
            "ending_phase": state["ending_phase"],
            "ending_id": state["ending_id"],
            "turn": self._turn_view(state),
            "can_advance": state["ending_phase"] != "committed",
            "goals": {},
        }

    def _presentation(self, state: dict[str, Any]) -> dict[str, Any]:
        emotion = state["npc"]["current_emotion"]
        return {
            "scene_id": state["scene"],
            "sprite_id": gs.sprite_for(emotion),
            "event_title": None,
            "event_badge": False,
        }

    def _interact_response(
        self,
        state: dict[str, Any],
        request_id: str,
        reply: AgentReply,
        analysis: meaningful_turn.Analysis,
        narration: list[str],
        changes: list[dict[str, Any]],
        planning_status: str,
        storylet: Any,
        ending_block: dict[str, Any] | None,
        notes: list[str],
    ) -> dict[str, Any]:
        presentation = self._presentation(state)
        if storylet is not None:
            presentation["event_title"] = storylet.title
            presentation["event_badge"] = True
        return {
            "game_id": state["game_id"],
            "request_id": request_id,
            "state_version": state["state_version"],
            "speaker": "xuzhi",
            "dialogue": reply.dialogue,
            "emotion": state["npc"]["current_emotion"],
            "narration": narration,
            "presentation": presentation,
            # 只下发玩家可感知的变化：内部数值与事实名不进玩家可见层
            "committed_changes": self._public_changes(changes),
            "active_event_id": state["active_storylet"],
            "can_advance": state["ending_phase"] != "committed",
            "planning_status": planning_status,
            "scheduled_event_id": state["scheduled_storylet"],
            "turn": self._turn_view(state),
            "state": self._public_state(state),
            "ending": ending_block,
            "ui_hints": {
                "dialogue_source": reply.source,
                "meaningful": analysis.is_meaningful,
                "meaningful_reason": analysis.meaningful_reason,
                "mood_shift": self._mood_shift(changes),
                "notes": notes,
                "llm": {
                    "model": reply.model or None,
                    "latency_ms": reply.latency_ms,
                    "input_tokens": reply.prompt_tokens,
                    "output_tokens": reply.completion_tokens,
                },
            },
        }

    @staticmethod
    def _public_changes(changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        allowed = {"scene", "ending_phase"}
        return [c for c in changes if c.get("path") in allowed]

    @staticmethod
    def _mood_shift(changes: list[dict[str, Any]]) -> str | None:
        """把内部数值变化翻译成玩家可感知的定性描述，不暴露具体数值。"""
        net = 0
        for change in changes:
            path = str(change.get("path", ""))
            if not path.startswith("relationship."):
                continue
            try:
                net += int(change.get("after", 0)) - int(change.get("before", 0))
            except (TypeError, ValueError):
                continue
        if net >= 5:
            return "她的态度明显松动了一点"
        if net >= 2:
            return "气氛缓和了一些"
        if net <= -5:
            return "她明显收起了原本的松动"
        if net <= -2:
            return "她的语气冷了一点"
        return None

    def _persist_turn_logs(
        self,
        game_id: str,
        state: dict[str, Any],
        text: str,
        reply: AgentReply,
        analysis: meaningful_turn.Analysis,
        narration: list[str],
        events: list[dict[str, Any]],
        memories: list[dict[str, Any]],
    ) -> None:
        idx = state["turn_index"]
        self.db.add_turn(game_id, idx, "player", text, {
            "topics": sorted(analysis.topics),
            "meaningful": analysis.is_meaningful,
            "reason": analysis.meaningful_reason,
        })
        for line in narration:
            self.db.add_turn(game_id, idx, "narration", line)
        self.db.add_turn(game_id, idx, "xuzhi", reply.dialogue, {
            "source": reply.source,
            "emotion": state["npc"]["current_emotion"],
        })

        for ev in events:
            self.db.add_event(game_id, ev["event_id"], ev["kind"], ev["status"], ev["payload"],
                              state["state_version"])

        if analysis.is_meaningful:
            memories.append({
                "kind": "episode",
                "content": f"玩家说「{analysis.normalized[:40]}」，她回应「{reply.dialogue[:40]}」",
                "importance": 2,
                "tags": sorted(analysis.topics),
            })
        for mem in memories:
            memory_store.remember(
                self.db, game_id, mem["kind"], mem["content"],
                importance=int(mem.get("importance", 3)),
                turn_index=idx,
                source_event_id=mem.get("source_event_id"),
                tags=list(mem.get("tags") or []),
            )
