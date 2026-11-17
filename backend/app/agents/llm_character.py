"""M1 角色 Agent：调用 OpenAI 兼容的 Chat Completions（默认 DeepSeek）。

职责边界：
- 只产出「这句台词 + 情绪 + 动作/事件结果提议」；
- 任何提议都要经过校验：动作白名单、事件结果白名单、泄露词过滤；
- 失败（超时/坏 JSON/违规）一律退回模板对白，界面永远不卡死。
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from .. import config
from .. import game_state as gs
from ..content import Content, load_content
from ..db import Database
from ..memory import store as memory_store
from ..narrative.storylets import Storylet
from ..rules.actions import ACTIONS
from ..rules.meaningful_turn import Analysis
from . import mock_character, prompts
from .mock_character import AgentReply

# 出现这些词说明模型在把系统内部信息当台词说，直接退回兜底
LEAK_WORDS = (
    "好感度", "信任值", "数值", "属性值", "storylet", "Storylet", "ending", "prompt",
    "系统提示", "状态机", "数据库", "JSON", "GPT", "AI 模型", "作为AI", "作为 AI",
)

MAX_DIALOGUE_CHARS = 180

# 明确的攻击性/赶人词：命中就重写一次；仍不改则退回模板（宁可平淡，也不能伤人）
HARSH_WORDS = (
    "滚", "烦不烦", "少管", "闭嘴", "烦死了", "关你什么事", "谁要你",
    "有病", "别烦我", "你算老几", "要你管",
)


class LLMResponseError(Exception):
    pass


def _is_harsh(dialogue: str) -> bool:
    return any(word in dialogue for word in HARSH_WORDS)


_CONTENT: Content | None = None


def _content() -> Content:
    global _CONTENT
    if _CONTENT is None:
        _CONTENT = load_content()
    return _CONTENT


def _endpoint() -> str:
    return config.LLM_BASE_URL.rstrip("/") + "/chat/completions"


def _post(messages: list[dict[str, str]]) -> dict[str, Any]:
    payload = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "temperature": config.LLM_TEMPERATURE,
        "max_tokens": config.LLM_MAX_OUTPUT_TOKENS,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": "Bearer " + config.LLM_API_KEY,
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=config.LLM_TIMEOUT_SECONDS) as client:
        resp = client.post(_endpoint(), headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()


def _extract_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


def _clean_dialogue(raw: Any) -> str:
    if not isinstance(raw, str):
        raise LLMResponseError("dialogue_not_str")
    dialogue = raw.strip().strip('"').strip()
    dialogue = re.sub(r"^```[a-zA-Z]*\s*", "", dialogue)
    dialogue = re.sub(r"\s*```$", "", dialogue).strip()
    if not dialogue:
        raise LLMResponseError("empty_dialogue")
    if len(dialogue) > MAX_DIALOGUE_CHARS:
        dialogue = dialogue[:MAX_DIALOGUE_CHARS].rstrip("，,。.；; ") + "……"
    for word in LEAK_WORDS:
        if word in dialogue:
            raise LLMResponseError("leak:" + word)
    return dialogue


def _validate(
    parsed: dict[str, Any],
    state: dict[str, Any],
    analysis: Analysis,
    storylet: Storylet | None,
) -> AgentReply:
    dialogue = _clean_dialogue(parsed.get("dialogue"))

    emotion = parsed.get("emotion")
    if emotion not in gs.EMOTIONS:
        emotion = gs.derive_emotion(state)

    proposed = parsed.get("actions") or []
    if not isinstance(proposed, list):
        proposed = []
    proposed = [a for a in proposed if isinstance(a, str)]
    known = [a for a in proposed if a in ACTIONS]
    # 只有玩家这句话真的做了这件事，才接受模型提议的动作；
    # small_talk 无副作用，允许模型自由使用（仍受每回合上限约束）。
    accepted = [a for a in known if a in set(analysis.actions) or a == "small_talk"][:3]
    rejected = [a for a in known if a not in set(analysis.actions) and a != "small_talk"]

    outcome = parsed.get("storylet_outcome")
    if storylet is None or not isinstance(outcome, str) or outcome not in storylet.possible_outcomes:
        outcome = None

    notes = []
    if rejected:
        notes.append("actions_without_evidence:" + ",".join(rejected))
    if parsed.get("storylet_outcome") and outcome is None:
        notes.append("outcome_not_allowed")

    return AgentReply(
        dialogue=dialogue,
        emotion=emotion,
        actions=accepted,
        storylet_outcome=outcome,
        source="llm",
        notes=notes,
    )


def llm_reply(
    state: dict[str, Any],
    analysis: Analysis,
    storylet: Storylet | None,
    expected_ending: str | None = None,
    db: Database | None = None,
    game_id: str | None = None,
) -> AgentReply:
    content = _content()
    recent: list[dict[str, Any]] = []
    memories: list[dict[str, Any]] = []
    if db is not None and game_id:
        recent = db.recent_turns(game_id, limit=config.LIMITS.history_turns_for_prompt)
        memories = memory_store.recall(db, game_id, analysis.normalized, k=config.LIMITS.memories_for_prompt)

    messages = prompts.build_messages(state, analysis, storylet, content, recent, memories)

    started = time.monotonic()
    last_error = ""
    usage: dict[str, Any] = {}
    tone_retried = False

    for attempt in range(1 + max(0, config.LLM_MAX_RETRIES)):
        try:
            data = _post(messages)
        except httpx.TimeoutException:
            last_error = "timeout"
            continue
        except httpx.HTTPStatusError as exc:
            last_error = f"http_{exc.response.status_code}"
            if exc.response.status_code in (429, 500, 502, 503, 504):
                time.sleep(0.5)
                continue
            break
        except Exception as exc:  # 网络/DNS/代理等
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
                {"role": "assistant", "content": str(raw)[:800]},
                {"role": "user", "content": "上面的输出不是合法 JSON。请只输出一个 JSON 对象，不要 markdown，不要解释。"},
            ]
            continue

        try:
            reply = _validate(parsed, state, analysis, storylet)
        except LLMResponseError as exc:
            last_error = str(exc)
            continue

        # 语气兜底：刻薄/赶人的台词先要求重写一次
        if _is_harsh(reply.dialogue):
            if not tone_retried:
                tone_retried = True
                last_error = "too_harsh"
                messages = messages + [
                    {"role": "assistant", "content": str(raw)[:600]},
                    {"role": "user",
                     "content": "这句太冲、像在伤人。保持嘴硬和回避，但不要讽刺、贬低或赶人；"
                                "同时给玩家留一个能接的话头。重写这一句，只输出 JSON。"},
                ]
                continue
            soft = mock_character.reply(state, analysis, storylet, expected_ending)
            soft.source = "fallback:too_harsh"
            soft.error = "too_harsh"
            soft.latency_ms = int((time.monotonic() - started) * 1000)
            soft.model = config.LLM_MODEL
            soft.prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
            soft.completion_tokens = int(usage.get("completion_tokens", 0) or 0)
            return soft

        reply.latency_ms = int((time.monotonic() - started) * 1000)
        reply.model = config.LLM_MODEL
        reply.prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        reply.completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        return reply

    fallback = mock_character.reply(state, analysis, storylet, expected_ending)
    fallback.source = f"fallback:{last_error}"
    fallback.error = last_error
    fallback.latency_ms = int((time.monotonic() - started) * 1000)
    fallback.model = config.LLM_MODEL
    fallback.prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
    fallback.completion_tokens = int(usage.get("completion_tokens", 0) or 0)
    return fallback
