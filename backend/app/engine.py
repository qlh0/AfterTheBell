"""游戏引擎：把「玩家输入 → 角色对白 → 规则提交 → 事件/结局」串成一次完整回合。

一次 /interact 的固定顺序（普通对话只调用一次角色 Agent，不串行调导演）：
    读状态 → 激活已排期事件 → 解析输入 → 角色回复（1 次 Agent）
    → 白名单动作提交 → 事件收尾 → 回合计数 → 场景推进
    → 目标/结局资格 → （必要时）确定性规划下一事件 → 乐观并发提交 → 返回完整 JSON
"""

from __future__ import annotations

import uuid
from typing import Any

from . import config
from . import game_state as gs
from . import records
from .agents import character
from .agents.mock_character import AgentReply
from .content import Content, load_content
from .db import Database, new_game_id
from .memory import store as memory_store
from .narrative import director_llm, scheduler
from .rules import actions as action_rules
from .rules import class_talk
from .rules import day_plan
from .rules import goals as goal_rules
from .rules import endings as ending_rules
from .rules import meaningful_turn, storylet_resolution, suggestions as suggestion_rules
from .rules import npc_intents
from .rules import storylet_progress as progress_rules
from .rules import threads as thread_rules

OPENING_NARRATION = [
    "放学铃响过二十分钟，教室里只剩下你们两个。这一周她回消息一直很慢，放学也总是先走——你还没找到机会问她。",
    "收书包时，她把桌角一张对折的纸压到课本最下面。你瞥见抬头印着「分班意向表」。",
    "你想起前几天在走廊，你随口跟陈屿说过一句「高中谈恋爱很麻烦」——当时她好像就在旁边。",
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


class GameNotEnded(Exception):
    def __init__(self, game_id: str) -> None:
        super().__init__(f"本局还没有结束：{game_id}")
        self.game_id = game_id


class DayPlanNotAvailable(Exception):
    pass


class Engine:
    def __init__(self, db: Database, content: Content | None = None) -> None:
        self.db = db
        self.content = content or load_content()

    # ---------------- 对外：开始 ----------------

    def start(self) -> dict[str, Any]:
        game_id = new_game_id()
        state = gs.default_state(game_id, self.content.goal_ids(), self.content.budget())
        thread_rules.sync(state)
        state["npc"]["current_emotion"] = gs.derive_emotion(state)
        self.db.create_game(state)
        branch = state["branch_id"]
        self.db.add_event(game_id, "game_started", "system", "committed",
                          {"scene": state["scene"]}, 0, branch_id=branch)
        for line in OPENING_NARRATION:
            self.db.add_turn(game_id, 0, "narration", line, branch_id=branch)
        self.db.add_turn(game_id, 0, "xuzhi", OPENING_LINE, {"opening": True}, branch_id=branch)
        return {
            "game_id": game_id,
            "state_version": state["state_version"],
            "narration": list(OPENING_NARRATION),
            "dialogue": OPENING_LINE,
            "emotion": "guarded",
            "presentation": self._presentation(state),
            "state": self._public_state(state),
            "suggestions": suggestion_rules.suggestions(state),
        }

    # ---------------- 对外：一次对话 ----------------

    def interact(
        self,
        game_id: str,
        text: str,
        request_id: str,
        expected_state_version: int | None = None,
    ) -> dict[str, Any]:
        state = self.db.load_state(game_id)
        if state is None:
            raise GameNotFound(game_id)
        branch_id = state.get("branch_id", "main")
        cached = self.db.get_cached_response(game_id, request_id, branch_id)
        if cached is not None:
            return cached
        if state["ending_phase"] == "committed":
            raise EndingCommitted(state.get("ending_id"))
        if expected_state_version is not None and expected_state_version != state["state_version"]:
            raise VersionConflict(state["state_version"], state)

        base_version = state["state_version"]
        changes: list[dict[str, Any]] = []
        narration: list[str] = []
        if state.get("pending_day_opening"):
            narration.append(state.pop("pending_day_opening"))
        events: list[dict[str, Any]] = []
        memories: list[dict[str, Any]] = []

        # 1. 新回合开始：激活已排期事件（或进入收束/finale）
        before_scene = state["scene"]
        before_day = int(state.get("day", 1))
        returned_text = self._apply_pending_return(state)
        if returned_text:
            narration.append(returned_text)
            changes.append({
                "path": "scene",
                "before": f"day{before_day}:{before_scene}",
                "after": f"day{state.get('day', 1)}:{state['scene']}",
                "reason": "return_after_activity",
            })
            events.append({
                "event_id": "scene_transition",
                "kind": "scene",
                "status": "committed",
                "payload": {"day": state.get("day", 1), "to": state["scene"],
                            "reason": "return_after_activity"},
            })
        analysis = meaningful_turn.analyze(text)
        activation = None
        if config.STORYLETS_ENABLED and state["ending_phase"] != "committed":
            hard_due = state["turn_index"] >= int(state["budget"]["hard_end_at"]) - 2
            if hard_due:
                moved, closure = self._force_closure_if_due(state)
                if closure:
                    narration.append(closure)
                activation = scheduler.force_finale(state, self.content.storylets)
            else:
                # 玩家明确说「去图书馆/走廊/小卖部」时，优先于排期事件
                activation = scheduler.trigger_by_text(
                    state, self.content.storylets, analysis.normalized
                )
                if activation is None:
                    activation = scheduler.try_activate(state, self.content.storylets)

        # 2. 玩家输入解析已完成（规则，不依赖模型）

        if activation is not None:
            narration.extend(activation.exposition)
            if activation.storylet.enter_narration:
                narration.append(activation.storylet.enter_narration)
            narration.append(activation.cue)
            changes.append({
                "path": "active_storylet",
                "before": None,
                "after": activation.storylet.id,
                "reason": f"activated:{activation.how}",
            })
            if state["scene"] != before_scene or int(state.get("day", 1)) != before_day:
                changes.append({
                    "path": "scene",
                    "before": f"day{before_day}:{before_scene}",
                    "after": f"day{state.get('day', 1)}:{state['scene']}",
                    "reason": f"scene:{activation.how}",
                })
            events.append({
                "event_id": activation.storylet.id,
                "kind": "storylet",
                "status": "activated",
                "payload": {"how": activation.how, "title": activation.storylet.title},
            })

        active = self.content.storylets.get(state["active_storylet"])

        # 3. 小卖部是校外场景：默认留在小卖部；只有玩家明确说回去才移动。
        if (
            not state.get("active_storylet")
            and state["scene"] == "shop"
            and self._mentions_return_to_school(analysis)
        ):
            old_day = int(state.get("day", 1))
            state["scene"] = "school_gate"
            state["return_scene"] = None
            narration.append("你们拎着东西从小卖部出来，走回校门口。")
            changes.append({
                "path": "scene",
                "before": f"day{old_day}:shop",
                "after": f"day{old_day}:school_gate",
                "reason": "return_from_shop",
            })
            events.append({
                "event_id": "scene_transition",
                "kind": "scene",
                "status": "committed",
                "payload": {"day": old_day, "to": "school_gate", "reason": "return_from_shop"},
            })

        # 4. 角色回复：普通对话只在这里调用一次 Agent
        expected_ending = None
        if active is not None and active.kind == "finale":
            expected_ending = ending_rules.preview_ending(state, self.content)
        reply = character.reply(
            state, analysis, active, expected_ending, db=self.db, game_id=game_id
        )
        self._record_llm(game_id, reply, branch_id)
        if getattr(reply, "beat", None):
            narration.append(reply.beat)

        # 3.5 分班只讲一次：事件外问到、她也说清了计划，也算「谈过分班」
        class_changes = class_talk.commit(state, analysis, reply.dialogue)
        if class_changes:
            changes.extend(class_changes)
            events.append({
                "event_id": "class_talk",
                "kind": "storylet",
                "status": "resolved",
                "payload": {"outcome": "class_talk", "reason": "玩家问到分班，她说清了自己的打算"},
            })

        # 4. 提交动作（白名单 + 每回合上限）
        #    规则动作优先；模型只能补充低风险动作（care / small_talk 等）。
        final_actions, action_notes = meaningful_turn.resolve_actions(analysis, reply.actions)
        action_changes, notes = action_rules.commit_actions(
            state, final_actions, reason=f"turn:{state['turn_index']}", analysis=analysis
        )
        notes.extend(action_notes)
        if reply.notes:
            notes.extend(reply.notes)
        changes.extend(action_changes)

        # 4.5 她的主动意图：只排期、不结算；上下文不成立就忽略
        npc_event = self._maybe_npc_initiative(state, reply)
        if npc_event is not None:
            events.append(npc_event)

        # 5. 事件推进：证据足够才结算；否则等待 / 超时放弃（绝不默认成功）
        ending_block: dict[str, Any] | None = None
        resolved_id: str | None = None
        if active is not None:
            resolved_set = state.setdefault("resolved_storylets", [])
            progress_rules.update_evidence(state, active, analysis, reply.actions)
            state["storylet_turns"] = int(state.get("storylet_turns", 0)) + 1

            if active.kind == "finale":
                ev = progress_rules.evaluate(state, active, analysis)
                if ev.outcome and active.id not in resolved_set:
                    resolution = ending_rules.resolve(state, self.content)
                    changes.extend(resolution.changes)
                    ending_block = ending_rules.ending_block(state, self.content)
                    narration.append("她说完最后一句，没有再躲开你的视线。")
                    resolved_id = active.id
                    resolved_set.append(active.id)
                    state["last_storylet_resolved_turn"] = state["turn_index"]
                    events.append({
                        "event_id": active.id,
                        "kind": "storylet",
                        "status": "resolved",
                        "payload": {
                            "ending": state["ending_id"],
                            "failed_goals": resolution.failed_goals,
                            "reason": ev.reason,
                            "evidence": ev.evidence or state.get("storylet_evidence", {}),
                        },
                    })
                    memories.append({
                        "kind": "ending",
                        "content": f"结局：{ending_block['title']}",
                        "importance": 5,
                        "tags": ["ending", state.get("ending_id") or ""],
                    })
                else:
                    state["storylet_stage"] = "interacting"
                    events.append({
                        "event_id": active.id, "kind": "storylet", "status": "pending",
                        "payload": {"reason": ev.reason, "evidence": state.get("storylet_evidence", {})},
                    })
            else:
                ev = progress_rules.evaluate(state, active, analysis)
                if ev.outcome and active.id not in resolved_set:
                    allowed = progress_rules.allowed_outcomes(state, active, analysis)
                    chosen = reply.storylet_outcome if reply.storylet_outcome in allowed else ev.outcome
                    resolution = storylet_resolution.resolve(state, active, analysis, chosen)
                    if resolution is not None:
                        changes.extend(resolution.changes)
                        narration.extend(resolution.narration)
                        scheduler.clear_active(state)
                        resolved_id = active.id
                        resolved_set.append(active.id)
                        state["last_storylet_resolved_turn"] = state["turn_index"]
                        events.append({
                            "event_id": active.id,
                            "kind": "storylet",
                            "status": "resolved",
                            "payload": {
                                "outcome": resolution.outcome,
                                "proposed_outcome": reply.storylet_outcome,
                                "reason": ev.reason,
                                "evidence": dict(state.get("storylet_evidence", {})),
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
                else:
                    abandon, why = progress_rules.should_abandon(state, active)
                    if abandon:
                        state.setdefault("abandoned_storylets", []).append({
                            "id": active.id,
                            "reason": why,
                            "turn": state["turn_index"],
                        })
                        scheduler.clear_active(state)
                        narration.append("她没再继续这个话题。")
                        events.append({
                            "event_id": active.id, "kind": "storylet", "status": "abandoned",
                            "payload": {"reason": why, "evidence": state.get("storylet_evidence", {})},
                        })
                    else:
                        state["storylet_stage"] = "interacting"
                        events.append({
                            "event_id": active.id, "kind": "storylet", "status": "pending",
                            "payload": {"reason": ev.reason, "evidence": state.get("storylet_evidence", {})},
                        })

        # 6. 回合计数
        state["turn_index"] += 1
        if analysis.is_meaningful:
            state["meaningful_turns"] += 1

        # 7. 场景推进：保证第一天的校门口、第二天的教室/校门口自然出现
        before_scene, before_day = state["scene"], int(state.get("day", 1))
        moved, scene_text = self._maybe_auto_advance(state, analysis)
        if moved:
            narration.append(scene_text)
            changes.append({
                "path": "scene",
                "before": f"day{before_day}:{before_scene}",
                "after": f"day{state.get('day', 1)}:{state['scene']}",
                "reason": "auto_time",
            })
            events.append({
                "event_id": "scene_transition",
                "kind": "scene",
                "status": "committed",
                "payload": {"day": state.get("day", 1), "to": state["scene"]},
            })

        # 7.5 第一天校门口：玩家说“明天见”，或到第 15 轮，她主动收束到第二天
        if (
            state["ending_phase"] != "committed"
            and not state.get("active_storylet")
            and int(state.get("day", 1)) == 1
            and state["scene"] == "school_gate"
        ):
            goodbye = any(
                word in analysis.normalized
                for word in ("明天见", "明天见啦", "明天见吧", "先走了", "我先走",
                             "路上小心", "再见", "拜拜", "回家了", "回家")
            )
            if goodbye or state["turn_index"] >= 15:
                transition_before_scene = state["scene"]
                moved, scene_text = self._advance_main_scene(state)
                if moved:
                    narration.append(scene_text)
                    changes.append({
                        "path": "scene",
                        "before": f"day1:{transition_before_scene}",
                        "after": f"day{state.get('day', 1)}:{state['scene']}",
                        "reason": "goodbye" if goodbye else "proactive_next_day",
                    })
                    events.append({
                        "event_id": "scene_transition",
                        "kind": "scene",
                        "status": "committed",
                        "payload": {
                            "day": state.get("day", 1),
                            "to": state["scene"],
                            "reason": "goodbye" if goodbye else "proactive_next_day",
                        },
                    })

        # 8. 目标与结局资格
        changes.extend(goal_rules.record_goal_progress(state, self.content))
        if ending_rules.maybe_make_eligible(state):
            changes.append({
                "path": "ending_phase",
                "before": "none",
                "after": "eligible",
                "reason": "finale_reachable",
            })
            events.append({"event_id": "ending_eligible", "kind": "ending", "status": "eligible",
                           "payload": {}})

        # 9. 规划下一事件：关键节点才请导演；普通闲聊不触发
        planning_status = "not_required"
        director_choice = None
        if state["ending_phase"] != "committed" and config.STORYLETS_ENABLED:
            reason = (
                "storylet_resolved" if resolved_id
                else ("advance" if moved else "turn")
            )
            plan = scheduler.plan_next(
                state,
                self.content.storylets,
                reason,
                chooser=lambda st, el: director_llm.choose(
                    st, el, self.content, self.db, game_id, why=reason
                ),
            )
            planning_status = plan.status
            director_choice = plan.director
            self._record_director(game_id, director_choice, branch_id)
            if plan.status != "not_required":
                events.append({
                    "event_id": plan.storylet_id or "no_event",
                    "kind": "director",
                    "status": plan.status,
                    "payload": {
                        "reason": plan.reason,
                        "choice": plan.storylet_id,
                        "source": getattr(director_choice, "source", "deterministic"),
                        "director_reason": getattr(director_choice, "reason", ""),
                        "based_on_version": state["state_version"],
                    },
                })

        # 9.5 硬上限兜底：第 22 轮必须结束；先保证第二天校门口 + 一句收束旁白
        force_at = (
            int(state["budget"]["soft_end_at"])
            if not config.STORYLETS_ENABLED
            else int(state["budget"]["hard_end_at"])
        )
        if state["ending_phase"] != "committed" and (
            gs.progress(state) >= force_at or state["turn_index"] >= force_at
        ):
            moved, closure = self._force_closure_if_due(state)
            if closure:
                narration.append(closure)
            resolution = ending_rules.resolve(state, self.content)
            changes.extend(resolution.changes)
            ending_block = ending_rules.ending_block(state, self.content)
            narration.append("她看着你，像是终于把憋了很久的话说完了。")
            events.append({
                "event_id": "forced_finale",
                "kind": "ending",
                "status": "committed",
                "payload": {
                    "reason": "hard_end_without_finale",
                    "ending": state["ending_id"],
                    "closure": True,
                },
            })

        # 9.6 线索状态与事实对齐（幂等；读档分支自带快照）
        changes.extend(thread_rules.sync(state))

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

        self._persist_turn_logs(game_id, state, text, reply, analysis, narration, events, memories, branch_id)

        # 结局提交后保存一份对局记录（失败不影响对局；/record 可按需重建）
        if ending_block is not None and state["ending_phase"] == "committed":
            try:
                records.save(self.db, state, self.content, ending_block)
            except Exception:
                pass
        return response

    # ---------------- 对外：推进/离场 ----------------

    def advance(
        self,
        game_id: str,
        request_id: str,
        intent: str = "continue",
        expected_state_version: int | None = None,
    ) -> dict[str, Any]:
        state = self.db.load_state(game_id)
        if state is None:
            raise GameNotFound(game_id)
        branch_id = state.get("branch_id", "main")
        cached = self.db.get_cached_response(game_id, request_id, branch_id)
        if cached is not None:
            return cached
        if state["ending_phase"] == "committed":
            raise EndingCommitted(state.get("ending_id"))
        if expected_state_version is not None and expected_state_version != state["state_version"]:
            raise VersionConflict(state["state_version"], state)

        base_version = state["state_version"]
        narration: list[str] = []
        changes: list[dict[str, Any]] = []
        if state.get("pending_day_opening"):
            narration.append(state.pop("pending_day_opening"))
        events: list[dict[str, Any]] = []

        before_scene = state["scene"]
        before_day = int(state.get("day", 1))
        if state.get("active_storylet"):
            narration.append("她还在等你说完，现在先不急着换地方。")
        else:
            moved, scene_text = self._advance_main_scene(state)
            if moved:
                narration.append(scene_text)
                changes.append({
                    "path": "scene",
                    "before": f"day{before_day}:{before_scene}",
                    "after": f"day{state.get('day', 1)}:{state['scene']}",
                    "reason": "player_advance",
                })
                events.append({
                    "event_id": "scene_transition",
                    "kind": "scene",
                    "status": "committed",
                    "payload": {"day": state.get("day", 1), "to": state["scene"]},
                })
            else:
                narration.append("今天已经没有别的安排了。你们在校门口又站了一会儿。")

        activation = None
        if config.STORYLETS_ENABLED and not state.get("active_storylet"):
            activation = scheduler.try_activate(state, self.content.storylets)
        planning_status = "not_required"
        if activation is not None:
            narration.extend(activation.exposition)
            if activation.storylet.enter_narration:
                narration.append(activation.storylet.enter_narration)
            narration.append(activation.cue)
            changes.append({"path": "active_storylet", "before": None,
                            "after": activation.storylet.id, "reason": f"activated:{activation.how}"})
            if state["scene"] != before_scene or int(state.get("day", 1)) != before_day:
                changes.append({
                    "path": "scene",
                    "before": f"day{before_day}:{before_scene}",
                    "after": f"day{state.get('day', 1)}:{state['scene']}",
                    "reason": f"scene:{activation.how}",
                })
            events.append({"event_id": activation.storylet.id, "kind": "storylet",
                           "status": "activated", "payload": {"how": activation.how}})
            planning_status = "activated"
        elif not state.get("active_storylet"):
            plan = scheduler.plan_next(
                state,
                self.content.storylets,
                "advance",
                chooser=lambda st, el: director_llm.choose(
                    st, el, self.content, self.db, game_id, why="advance"
                ),
            ) if config.STORYLETS_ENABLED else None
            if plan is not None:
                planning_status = plan.status
                self._record_director(game_id, plan.director, branch_id)
                if plan.status != "not_required":
                    events.append({
                        "event_id": plan.storylet_id or "no_event",
                        "kind": "director",
                        "status": plan.status,
                        "payload": {
                            "reason": plan.reason,
                            "choice": plan.storylet_id,
                            "source": getattr(plan.director, "source", "deterministic"),
                            "director_reason": getattr(plan.director, "reason", ""),
                            "based_on_version": state["state_version"],
                        },
                    })

        changes.extend(goal_rules.record_goal_progress(state, self.content))
        changes.extend(thread_rules.sync(state))
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
            "suggestions": suggestion_rules.suggestions(state, active),
        }
        response["presentation"]["event_title"] = active.title if active else None
        response["presentation"]["event_badge"] = active is not None

        if not self.db.save_state_cas(state, base_version, request_id, "advance", response):
            latest = self.db.load_state(game_id) or state
            raise VersionConflict(latest.get("state_version", -1), latest)

        self.db.add_turn(game_id, state["turn_index"], "narration",
                         "\n".join(narration) or "（你们站了一会儿。）", branch_id=branch_id)
        for ev in events:
            self.db.add_event(game_id, ev["event_id"], ev["kind"], ev["status"], ev["payload"],
                              state["state_version"], branch_id=branch_id)
        return response

    def submit_day_plan(
        self,
        game_id: str,
        text: str,
        request_id: str,
        expected_state_version: int | None = None,
    ) -> dict[str, Any]:
        """第二天开始时保存玩家的一句轻量计划；只影响开场和提示，不改事实/关系。"""
        state = self.db.load_state(game_id)
        if state is None:
            raise GameNotFound(game_id)
        branch_id = state.get("branch_id", "main")
        cached = self.db.get_cached_response(game_id, request_id, branch_id)
        if cached is not None:
            return cached
        if state["ending_phase"] == "committed":
            raise EndingCommitted(state.get("ending_id"))
        if expected_state_version is not None and expected_state_version != state["state_version"]:
            raise VersionConflict(state["state_version"], state)
        if int(state.get("day", 1)) != 2 or state["scene"] != "classroom":
            raise DayPlanNotAvailable("第二天计划只能在第二天教室开始时提交")
        current = state.get("day2_plan") or {}
        if current.get("status") == "consumed":
            raise DayPlanNotAvailable("第二天计划已经提交过")
        if current.get("status") not in (None, "none", "pending"):
            raise DayPlanNotAvailable("当前不能提交第二天计划")

        base_version = state["state_version"]
        plan = day_plan.plan_payload(text)
        state["day2_plan"] = plan
        state.pop("pending_day_opening", None)
        state["state_version"] = base_version + 1

        response = {
            "game_id": game_id,
            "request_id": request_id,
            "state_version": state["state_version"],
            "narration": [plan["opening"]],
            "opening": plan["opening"],
            "day2_plan": dict(plan),
            "presentation": self._presentation(state),
            "suggestions": suggestion_rules.suggestions(state, None),
            "turn": self._turn_view(state),
            "state": self._public_state(state),
        }
        if not self.db.save_state_cas(state, base_version, request_id, "day-plan", response):
            latest = self.db.load_state(game_id) or state
            raise VersionConflict(latest.get("state_version", -1), latest)
        self.db.add_event(
            game_id,
            "day2_plan",
            "system",
            "committed",
            {"tags": plan["tags"], "status": plan["status"]},
            state["state_version"],
            branch_id=branch_id,
        )
        return response

    # ---------------- 对外：读取 ----------------

    def get_state(self, game_id: str, include_internal: bool = False) -> dict[str, Any]:
        state = self.db.load_state(game_id)
        if state is None:
            raise GameNotFound(game_id)
        payload = {
            "game_id": game_id,
            "branch_id": state.get("branch_id", "main"),
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
        branch = state.get("branch_id", "main")
        return {"game_id": game_id, "branch_id": branch,
                "events": self.db.list_events(game_id, branch_id=branch),
                "metrics": self.db.llm_metrics(game_id, branch_id=branch)}

    def get_metrics(self, game_id: str) -> dict[str, Any]:
        """M3 指标面板：分用途的调用数、延迟分位、token、失败原因 + 本局进度。"""
        state = self.db.load_state(game_id)
        if state is None:
            raise GameNotFound(game_id)
        stats = self.db.llm_stats(game_id, branch_id=state.get("branch_id", "main"))
        stats["session"] = {
            "branch_id": state.get("branch_id", "main"),
            "scene": state["scene"],
            "turn_index": state["turn_index"],
            "meaningful_turns": state["meaningful_turns"],
            "progress": gs.progress(state),
            "budget": state["budget"],
            "ending_phase": state["ending_phase"],
            "ending_id": state["ending_id"],
            "used_storylets": list(state.get("used_storylets") or []),
            "active_storylet": state["active_storylet"],
            "scheduled_storylet": state["scheduled_storylet"],
        }
        return stats

    def get_record(self, game_id: str, branch_id: str | None = None) -> dict[str, Any]:
        """读取本局记录；如果结局记录缺失，从当前状态与日志重建并补存。"""
        state = self.db.load_state(game_id)
        if state is None:
            raise GameNotFound(game_id)
        branch = branch_id or state.get("branch_id", "main")
        record = self.db.get_record(game_id, branch)
        if record is not None:
            return record
        if state["ending_phase"] != "committed":
            raise GameNotEnded(game_id)
        return records.save(self.db, state, self.content, None)

    def list_records(self, limit: int = 30) -> dict[str, Any]:
        return {"records": self.db.list_records(limit)}

    def restore(self, game_id: str, version: int) -> dict[str, Any]:
        """读档：把服务端快照恢复成**新的时间线分支**（历史不丢、未来不泄漏）。"""
        snapshot = self.db.load_snapshot(game_id, version)
        if snapshot is None:
            raise GameNotFound(f"{game_id}@v{version}")
        current = self.db.load_state(game_id)
        if current is None:
            raise GameNotFound(game_id)
        base_version = current["state_version"]

        from_branch = snapshot.get("branch_id", "main")
        new_branch = "b" + uuid.uuid4().hex[:6]
        snapshot["branch_id"] = new_branch
        snapshot["state_version"] = base_version + 1
        # 旧时间线的进行中/已排期事件与导演计划一律不带入新分支
        snapshot["active_storylet"] = None
        snapshot["storylet_stage"] = "none"
        snapshot["storylet_evidence"] = {}
        snapshot["storylet_turns"] = 0
        snapshot["storylet_started_turn"] = None
        snapshot["scheduled_storylet"] = None
        snapshot["scheduled_at_version"] = None
        snapshot["last_plan_turn"] = -1

        if not self.db.save_state_cas(snapshot, base_version):
            latest = self.db.load_state(game_id) or snapshot
            raise VersionConflict(latest.get("state_version", -1), latest)
        # 把读档点之前的上下文复制进新分支（未来不复制）
        self.db.copy_branch_context(
            game_id,
            from_branch=from_branch,
            to_branch=new_branch,
            max_turn_index=int(snapshot.get("turn_index", 0)),
            max_state_version=version,
        )
        self.db.add_event(game_id, "restore", "system", "committed",
                          {"restored_version": version, "from_branch": current.get("branch_id", "main")},
                          snapshot["state_version"], branch_id=new_branch)
        return {"restored_from": version, "state_version": snapshot["state_version"],
                "branch_id": new_branch, "state": self._public_state(snapshot)}

    # ---------------- 内部 ----------------

    def _maybe_npc_initiative(self, state: dict[str, Any], reply: AgentReply) -> dict[str, Any] | None:
        """把她的主动意图变成「排期」，不直接提交任何事实。"""
        intent = getattr(reply, "npc_intent", None)
        if not intent or not config.STORYLETS_ENABLED:
            return None
        if state["active_storylet"] or state["scheduled_storylet"]:
            return None
        if state["ending_phase"] in ("prepared", "committed"):
            return None
        if int(state["turn_index"]) - int(state.get("last_npc_intent_turn", -10)) < 2:
            return None
        ok, _why = npc_intents.validate(state, intent)
        if not ok:
            return None

        state["last_npc_intent_turn"] = state["turn_index"]
        state["npc"]["last_intent"] = intent
        sid = npc_intents.storylet_for(intent)
        if sid and self.content.storylets.is_still_eligible(sid, state):
            state["scheduled_storylet"] = sid
            state["scheduled_at_version"] = state["state_version"]
            state["last_plan_turn"] = state["turn_index"]
            return {
                "event_id": sid,
                "kind": "npc",
                "status": "scheduled",
                "payload": {"intent": intent, "why": npc_intents.INTENTS[intent]["why"]},
            }
        return {"event_id": "npc_intent", "kind": "npc", "status": "noted",
                "payload": {"intent": intent}}

    def _record_llm(self, game_id: str, reply: AgentReply, branch_id: str = "main") -> None:
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
            branch_id=branch_id,
        )

    def _record_director(self, game_id: str, choice: Any, branch_id: str = "main") -> None:
        """记录导演调用指标（确定性打分不落库）。"""
        if choice is None or not getattr(choice, "model", ""):
            return
        self.db.add_llm_call(
            game_id=game_id,
            purpose="director",
            model=choice.model,
            latency_ms=choice.latency_ms,
            prompt_tokens=choice.prompt_tokens,
            completion_tokens=choice.completion_tokens,
            ok=getattr(choice, "source", "") == "llm",
            error=getattr(choice, "error", ""),
            branch_id=branch_id,
        )

    def _advance_main_scene(self, state: dict[str, Any]) -> tuple[bool, str]:
        """主场景推进：教室 → 校门口 → 第二天教室 → 第二天校门口。"""
        day = int(state.get("day", 1))
        scene = state["scene"]
        if scene in gs.OPTIONAL_SCENES:
            if scene == "shop":
                # 小卖部在校外：默认不回校门口；推进时间才离开
                target = (2, "school_gate") if day == 2 else (2, "classroom")
            else:
                target = (day, state.get("return_scene") or "school_gate")
        else:
            target = gs.SCENE_FLOW.get((day, scene))
        if target is None:
            return False, ""
        new_day, new_scene = target
        day_changed = new_day != day
        state["day"] = new_day
        state["scene"] = new_scene
        state["return_scene"] = None
        if day_changed:
            # 第二天的开场旁白留到下一天的第一回合展示，不能和第一天的告别挤在同一屏。
            state["pending_day_opening"] = "第二天放学后，教室里只剩下你们两个。"
            if int(state.get("day", 1)) == 2:
                state.setdefault("day2_plan", {
                    "text": "", "tags": [], "status": "none", "opening": "",
                })
                if state["day2_plan"].get("status") != "consumed":
                    state["day2_plan"]["status"] = "pending"
            if scene == "school_gate":
                return True, "她把书包带整理好，朝你摆了摆手：「明天放学后见。」"
            if scene == "shop":
                return True, "你们从小卖部出来。"
            return True, ""
        if day == 1 and scene == "classroom" and new_scene == "school_gate":
            return True, "放学铃响过，你们收好书包，一前一后下了楼。校门口的路灯刚亮。"
        if day == 2 and scene == "classroom" and new_scene == "school_gate":
            return True, "第二天傍晚，你们收好书包下楼。校门口的路灯一盏一盏亮起来。"
        if scene == "classroom" and new_day == 2:
            return True, "第二天放学后，教室里只剩下你们两个。"
        if scene == "school_gate" and new_scene == "classroom":
            return True, "第二天放学后，教室里只剩下你们两个。"
        return True, "你们回到校门口，风把白天的热气吹散了。"
        if day == 1 and scene == "classroom" and new_scene == "school_gate":
            return True, "放学铃响过，你们收好书包，一前一后下了楼。校门口的路灯刚亮。"
        if day == 2 and scene == "classroom" and new_scene == "school_gate":
            return True, "第二天傍晚，你们收好书包下楼。校门口的路灯一盏一盏亮起来。"
        if scene == "classroom" and new_day == 2:
            return True, "第二天放学后，教室里只剩下你们两个。"
        if scene == "school_gate" and new_scene == "classroom":
            return True, "第二天放学后，教室里只剩下你们两个。"
        return True, "你们回到校门口，风把白天的热气吹散了。"

    def _maybe_auto_advance(self, state: dict[str, Any], analysis: Any) -> tuple[bool, str]:
        """保证第一天校门口、第二天教室、第二天校门口在预算内自然出现。"""
        if state.get("active_storylet"):
            return False, ""
        day = int(state.get("day", 1))
        scene = state["scene"]
        p = gs.progress(state)
        if scene in gs.OPTIONAL_SCENES:
            return False, ""
        if (day, scene) == (1, "classroom") and (
            "leave" in analysis.topics or p >= 5 or state["turn_index"] >= 5
        ):
            return self._advance_main_scene(state)
        if (day, scene) == (1, "school_gate") and state["turn_index"] >= 15:
            return self._advance_main_scene(state)
        if (day, scene) == (2, "classroom") and state["turn_index"] >= 18:
            return self._advance_main_scene(state)
        return False, ""

    def _apply_pending_return(self, state: dict[str, Any]) -> str:
        """上一段插曲结束后，下一次进入校门口时再切场景，避免结算台词和背景错位。"""
        return_scene = state.get("return_scene")
        if not return_scene or state.get("active_storylet"):
            return ""
        state["return_scene"] = None
        if state["scene"] == return_scene:
            return ""
        state["scene"] = return_scene
        if return_scene == "school_gate":
            return "你们回到校门口，天色又暗了一点。"
        return ""

    def _restore_scene(self, state: dict[str, Any]) -> bool:
        return_scene = state.get("return_scene")
        if not return_scene:
            return False
        state["return_scene"] = None
        if state["scene"] == return_scene:
            return False
        state["scene"] = return_scene
        return True

    @staticmethod
    def _mentions_return_to_school(analysis: Any) -> bool:
        text = analysis.normalized
        return any(word in text for word in ("回校门口", "回学校", "回校", "校门口"))

    def _force_closure_if_due(self, state: dict[str, Any]) -> tuple[bool, str]:
        """第 22 轮前必须把场景拉到第二天校门口，并留一段收束对话。"""
        if state.get("ending_phase") == "committed":
            return False, ""
        hard = int(state["budget"]["hard_end_at"])
        if state["turn_index"] < hard - 2:
            return False, ""
        scene_changed = state.get("scene") != "school_gate" or int(state.get("day", 1)) != 2
        state["day"] = 2
        state["scene"] = "school_gate"
        state["return_scene"] = None
        if scene_changed:
            return True, "第二天傍晚，你们又站到了校门口。天已经暗下来，谁都没有先走。"
        return False, ""

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
            "day": int(state.get("day", 1)),
            "day_label": gs.DAY_LABELS[int(state.get("day", 1))],
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
            "day": int(state.get("day", 1)),
            "day_label": gs.DAY_LABELS[int(state.get("day", 1))],
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
            "suggestions": suggestion_rules.suggestions(state, storylet),
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
        branch_id: str = "main",
    ) -> None:
        idx = state["turn_index"]
        self.db.add_turn(game_id, idx, "player", text, {
            "topics": sorted(analysis.topics),
            "meaningful": analysis.is_meaningful,
            "reason": analysis.meaningful_reason,
        }, branch_id=branch_id)
        for line in narration:
            self.db.add_turn(game_id, idx, "narration", line, branch_id=branch_id)
        self.db.add_turn(game_id, idx, "xuzhi", reply.dialogue, {
            "source": reply.source,
            "emotion": state["npc"]["current_emotion"],
        }, branch_id=branch_id)

        for ev in events:
            self.db.add_event(game_id, ev["event_id"], ev["kind"], ev["status"], ev["payload"],
                              state["state_version"], branch_id=branch_id)

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
                branch_id=branch_id,
            )
