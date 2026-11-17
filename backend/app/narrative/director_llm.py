"""M2 Narrative Director：让 LLM 在「规则已过滤的合法候选」里选下一个事件。

边界（和 M0 的确定性打分完全一致）：
- 只能选 `eligible` 里的 id，或选择 no_event；
- 不写状态、不代替角色说话、不决定结局；
- 任何失败都退回确定性打分，绝不阻塞或搞坏这一轮对白。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .. import config
from .. import game_state as gs
from ..content import Content, load_content
from ..db import Database
from ..memory import store as memory_store
from . import director
from .storylets import Storylet

_SYSTEM_FILE = config.PROMPTS_DIR / "director_system.txt"

GOAL_CN = {
    "notice_distance": "发现关系异常",
    "clarify_misunderstanding": "认识或澄清误会",
    "discuss_class_change": "面对分班现实",
    "define_relationship": "最终关系抉择",
}
STATUS_CN = {"pending": "未开始", "in_progress": "进行中", "done": "已完成", "failed": "未完成"}


@dataclass
class DirectorChoice:
    storylet_id: str | None
    reason: str = ""
    source: str = "deterministic"  # llm | deterministic | fallback
    model: str = ""
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str = ""
    notes: list[str] = field(default_factory=list)


def _system_prompt() -> str:
    if _SYSTEM_FILE.exists():
        return _SYSTEM_FILE.read_text(encoding="utf-8")
    return "你是一个叙事导演。只能从给定候选里选择事件，或选择 no_event。"


def _candidate_lines(eligible: list[Storylet]) -> list[str]:
    lines: list[str] = []
    for st in eligible:
        lines.append(
            f"- id={st.id}｜《{st.title}》｜目标={st.narrative_goal}｜场景={','.join(st.allowed_scenes)}"
            f"｜情境={st.opening_cue}｜可用走向={','.join(st.possible_outcomes)}"
        )
    return lines


def _facts_summary(state: dict[str, Any]) -> list[str]:
    facts = state["facts"]
    mapping = {
        "player_asked_distance": "玩家问过她最近的疏远",
        "misunderstanding_discussed": "「那句话」被摆上台面谈过",
        "misunderstanding_resolved": "误会已经解开",
        "class_change_discussed": "两人认真谈过分班",
        "player_expressed_romance": "玩家表达过心意",
        "player_controlling": "玩家曾试图替她做决定",
        "walk_home_done": "两人一起走过放学路",
        "old_note_seen": "旧便签已经出现过",
        "chenyu_hint_seen": "陈屿的线索已经出现过",
    }
    lines = [text for key, text in mapping.items() if facts.get(key)]
    return lines or ["还没有关键事实发生"]


def build_messages(
    state: dict[str, Any],
    eligible: list[Storylet],
    content: Content,
    recent_turns: list[dict[str, Any]],
    memories: list[dict[str, Any]],
) -> list[dict[str, str]]:
    goals = "\n".join(
        f"- {gid}（{GOAL_CN.get(gid, gid)}）：{STATUS_CN.get(status, status)}"
        for gid, status in state["narrative_goals"].items()
    )
    recent = []
    for turn in recent_turns[-6:]:
        role = turn.get("role")
        text = (turn.get("text") or "").strip()
        if not text:
            continue
        recent.append(f"{'玩家' if role == 'player' else '许栀' if role == 'xuzhi' else '旁白'}：{text}")

    used = set(state.get("used_storylets") or [])
    budget = state["budget"]
    p = gs.progress(state)
    if p >= int(budget["soft_end_at"]):
        pacing = "已经接近收尾预算，优先推进/解决旧线索，不要再开新支线。"
    elif p >= int(budget["soft_end_at"]) - 3:
        pacing = "进入中后段，可以开始收束。"
    else:
        pacing = "还在前中段，可以铺垫。"

    user = f"""【进度】第 {state['turn_index']} 轮，有效互动 {state['meaningful_turns']} 次；{pacing}
【当前场景】{'教室（放学后）' if state['scene'] == 'classroom' else '校门口（傍晚）'}

【叙事目标】
{goals}

【已发生的关键事实】
""" + "\n".join(f"- {x}" for x in _facts_summary(state)) + """

【最近说过的话】
""" + ("\n".join(recent) if recent else "- （刚刚开始）") + """

【相关记忆】
""" + ("\n".join(f"- {m['content']}" for m in memories) if memories else "- （暂无）") + """

【已用过的事件】（不要再选）
""" + ("、".join(sorted(used)) if used else "无") + """

【合法候选事件】（只能从这些 id 里选，或选 no_event）
""" + "\n".join(_candidate_lines(eligible)) + """

【任务】
选一个最合适的下一个事件，或者 no_event。考虑：
1. 是否推进了尚未完成的叙事目标；
2. 是否与玩家刚才的行为有因果关系；
3. 是否重复了刚演过的类型；
4. 临近收尾时优先处理旧线索，不要开新支线。
不要因为候选里有某个事件就必须选它。

【输出】只输出一个 JSON 对象，不要解释：
{"choice": "候选 id 或 no_event", "reason": "一句话理由"}"""

    return [
        {"role": "system", "content": _system_prompt()},
        {"role": "user", "content": user},
    ]


def _post(messages: list[dict[str, str]]) -> dict[str, Any]:
    payload = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "temperature": config.LLM_DIRECTOR_TEMPERATURE,
        "max_tokens": config.LLM_DIRECTOR_MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": "Bearer " + config.LLM_API_KEY,
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=config.LLM_TIMEOUT_SECONDS) as client:
        resp = client.post(config.LLM_BASE_URL.rstrip("/") + "/chat/completions",
                           headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()


def _extract_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        pass
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            data = json.loads(text[start : end + 1])
            return data if isinstance(data, dict) else None
        except Exception:
            return None
    return None


def _deterministic(state: dict[str, Any], eligible: list[Storylet], why: str) -> DirectorChoice:
    chosen = director.propose(state, eligible)
    if chosen is None:
        return DirectorChoice(storylet_id=None, reason=why, source="deterministic")
    return DirectorChoice(
        storylet_id=chosen.id,
        reason=f"确定性打分（{why}）：{chosen.title}",
        source="deterministic",
    )


def choose(
    state: dict[str, Any],
    eligible: list[Storylet],
    content: Content | None = None,
    db: Database | None = None,
    game_id: str | None = None,
    why: str = "",
) -> DirectorChoice:
    if not eligible:
        return DirectorChoice(storylet_id=None, reason="没有合法候选", source="deterministic")
    if not (config.DIRECTOR_ENABLED and config.llm_configured()):
        return _deterministic(state, eligible, why)

    content = content or load_content()
    recent: list[dict[str, Any]] = []
    memories: list[dict[str, Any]] = []
    if db is not None and game_id:
        recent = db.recent_turns(game_id, limit=6)
        memories = memory_store.recall(db, game_id, "下一件事", k=4)

    messages = build_messages(state, eligible, content, recent, memories)
    started = time.monotonic()
    last_error = ""

    for attempt in range(1 + max(0, config.LLM_MAX_RETRIES)):
        try:
            data = _post(messages)
        except httpx.TimeoutException:
            last_error = "timeout"
            continue
        except httpx.HTTPStatusError as exc:
            last_error = f"http_{exc.response.status_code}"
            if exc.response.status_code in (429, 500, 502, 503, 504):
                time.sleep(0.4)
                continue
            break
        except Exception as exc:
            last_error = f"network:{type(exc).__name__}"
            continue

        usage = data.get("usage") or {}
        try:
            raw = data["choices"][0]["message"]["content"]
        except Exception:
            last_error = "bad_envelope"
            continue

        parsed = _extract_json(raw)
        if parsed is None:
            last_error = "bad_json"
            messages = messages + [
                {"role": "assistant", "content": str(raw)[:400]},
                {"role": "user", "content": "上面的输出不是合法 JSON。请只输出 {\"choice\": ..., \"reason\": ...}。"},
            ]
            continue

        choice = str(parsed.get("choice", "")).strip()
        allowed = {st.id for st in eligible}
        if choice not in allowed and choice != "no_event":
            last_error = "choice_not_allowed"
            continue

        return DirectorChoice(
            storylet_id=None if choice == "no_event" else choice,
            reason=str(parsed.get("reason", ""))[:120],
            source="llm",
            model=config.LLM_MODEL,
            latency_ms=int((time.monotonic() - started) * 1000),
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
        )

    fallback = _deterministic(state, eligible, f"导演失败({last_error})，退回打分")
    fallback.source = "fallback"
    fallback.error = last_error
    fallback.model = config.LLM_MODEL
    fallback.latency_ms = int((time.monotonic() - started) * 1000)
    return fallback
