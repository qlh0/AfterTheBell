"""把「状态 + 记忆 + 最近对话 + 当前事件」组装成角色 LLM 的 prompt。

原则：
- 只给她「她自己会知道的东西」；客观真相只作为"绝对不能主动说"的警戒线出现。
- 不给数字，只给定性描述（低/一般/较高），避免模型把数值当台词说出来。
- 玩家没表达过的立场，不写进 prompt，模型也就无从替玩家表态。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from .. import game_state as gs
from ..config import PROMPTS_DIR
from ..content import Content
from ..narrative.storylets import Storylet
from ..rules.actions import ACTIONS
from ..rules.meaningful_turn import Analysis
from ..rules.npc_intents import prompt_lines as npc_intent_lines
from ..rules.diary import prompt_lines as diary_prompt_lines

_SYSTEM_FILE = PROMPTS_DIR / "character_system.txt"
_CRAFT_DIR = PROMPTS_DIR / "writing"


@lru_cache(maxsize=8)
def _craft(name: str) -> str:
    """按任务读取写作规范；缺失时返回空串，由测试保证仓库内文件存在。"""
    path = _CRAFT_DIR / f"{name}.txt"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _crafts_for(storylet: Storylet | None) -> list[str]:
    crafts = [_craft("dialogue")]
    if storylet is not None:
        crafts.append(_craft("ending" if storylet.kind == "finale" else "scene"))
    return [c for c in crafts if c]

EMOTION_CN = {
    "guarded": "戒备/回避",
    "normal": "平常",
    "relieved": "松了口气",
    "happy": "心情不错",
    "hurt": "被伤到",
    "sad": "低落",
    "annoyed": "有点恼",
    "soft": "心软",
    "shy": "害羞",
    "surprised": "意外",
}

SCENE_CN = {
    "classroom": "教室（放学后）",
    "school_gate": "校门口（傍晚）",
    "corridor": "走廊",
    "library": "图书馆",
    "shop": "小卖部",
}

TOPIC_CN = {
    "distance": "最近的疏远",
    "misunderstanding": "那句被误解的话",
    "class_change": "分班/重点班",
    "romance": "恋爱与心意",
    "chenyu": "陈屿",
    "care": "关心她",
    "apology": "道歉",
    "controlling": "替她做决定",
    "leave": "离开/回家",
    "smalltalk": "闲聊",
}

MUTUAL_INTENT_CN = {
    "unknown": "还没说清",
    "romance": "彼此有好感，但还没定下来",
    "friendship": "倾向于继续做朋友",
    "declined": "有点想退开",
}


def _qualify(value: int) -> str:
    if value < 25:
        return "很低"
    if value < 40:
        return "偏低"
    if value < 55:
        return "一般"
    if value < 70:
        return "较高"
    if value < 85:
        return "高"
    return "很高"


def _facts_lines(state: dict[str, Any]) -> list[str]:
    facts = state["facts"]
    lines: list[str] = []
    if facts["player_asked_distance"]:
        lines.append("玩家问过你最近为什么冷淡；你承认了一点点。")
    if facts["misunderstanding_discussed"]:
        lines.append("你们把「那句话」摆到台面上谈过。")
    if facts["misunderstanding_resolved"]:
        lines.append("那件事已经说开了：你知道玩家当时不是在说你。")
    if facts["class_change_discussed"]:
        lines.append("你们认真谈过你要报理科重点班这件事。")
    if facts["player_expressed_romance"]:
        lines.append("玩家明确对你表达过心意。")
    if facts["player_controlling"]:
        lines.append("玩家曾经想替你做决定，你当时很不舒服，明确说过「这是我的事」。")
    if facts["player_promised"]:
        lines.append("玩家对你做出过承诺。")
    if facts["walk_home_done"]:
        lines.append("你们一起走过一段放学路。")
    if facts["old_note_seen"]:
        lines.append("你翻出过一张去年的旧便签，那是你们以前传的。")
    if facts["chenyu_hint_seen"]:
        lines.append("陈屿提到过玩家，也提到过你最近的状态。")
    if not lines:
        lines.append("今天你们还没有把任何一件关键的事说明白。")
    return lines


def _recent_lines(recent_turns: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for turn in recent_turns:
        role = turn.get("role")
        text = (turn.get("text") or "").strip()
        if not text:
            continue
        if role == "player":
            lines.append(f"玩家：{text}")
        elif role == "xuzhi":
            lines.append(f"你：{text}")
        elif role == "narration":
            lines.append(f"（{text}）")
    return lines[-12:]


def _action_lines() -> list[str]:
    """只给出白名单，并说明"只能提议玩家真的表达过的动作"。"""
    return [f"- {aid}：{spec['label']}" for aid, spec in ACTIONS.items()]


def _pacing_note(state: dict[str, Any]) -> str:
    p = gs.progress(state)
    budget = state["budget"]
    if p >= int(budget["soft_end_at"]):
        return "时间不早了，你们已经聊了一阵。她心里知道再不说可能就没机会了，但也随时可能选择逃开。"
    if p >= int(budget["soft_end_at"]) - 3:
        return "天已经暗下来了。她开始意识到这场对话不会一直持续下去。"
    return "离天黑还有时间，气氛还没有被逼到必须摊牌。"


def system_prompt(content: Content, storylet: Storylet | None = None) -> str:
    char = content.characters["xuzhi"]
    base = _SYSTEM_FILE.read_text(encoding="utf-8") if _SYSTEM_FILE.exists() else ""
    lines = [
        base.strip(),
        "",
        "【补充设定】",
        f"人设：{char['persona']}",
        "说话方式：" + "；".join(char.get("speech_rules", [])),
        "你知道的事：" + "；".join(char.get("knows", [])),
        "你不知道的事：" + "；".join(char.get("does_not_know", [])),
        "",
        "【绝对不能主动说出口的】",
        *[f"- {s}" for s in char.get("secrets_not_for_player_view", [])],
        "",
        "【绝不能做的】",
        *[f"- 不要：{s}" for s in char.get("cannot_be_forced_into", [])],
        "- 不要替玩家说话、不要替玩家决定感情、不要读心。",
        "- 不要在台词里出现任何数字、属性名、系统词。",
        "- 只输出一个 JSON 对象，不要 markdown 代码块，不要解释。",
    ]
    crafts = _crafts_for(storylet)
    if crafts:
        lines += ["", "【写作规范】", *crafts]
    return "\n".join(lines)


def user_prompt(
    state: dict[str, Any],
    analysis: Analysis,
    storylet: Storylet | None,
    content: Content,
    recent_turns: list[dict[str, Any]],
    memories: list[dict[str, Any]],
) -> str:
    char = content.characters["xuzhi"]
    scene_cn = SCENE_CN.get(state["scene"], "校门口（傍晚）")
    if state["scene"] == "classroom" and int(state.get("day", 1)) == 2:
        scene_cn = "第二天教室（放学后）"
    rel = state["relationship"]
    emotion = gs.derive_emotion(state)

    parts: list[str] = [
        "【场景】" + scene_cn,
        f"【进度】这是今天对话的第 {state['turn_index']} 轮，其中真正有内容的互动 {state['meaningful_turns']} 次。",
        _pacing_note(state),
        "",
        "【你现在的状态】",
        f"- 情绪：{EMOTION_CN.get(emotion, '平常')}",
        f"- 你对玩家的信任：{_qualify(rel['trust'])}",
        f"- 你对玩家的亲近感：{_qualify(rel['affection'])}",
        f"- 你觉得玩家尊重你的选择吗：{_qualify(rel['respect_for_autonomy'])}",
        f"- 你自己对玩家的心意：{char['personal_goal_note']}",
        f"- 关系进度：{MUTUAL_INTENT_CN.get(state['npc']['mutual_intent'], '还没说清')}",
        "",
        "【你们之间已经发生的事】",
        *_facts_lines(state),
        "",
        "【玩家目前知道的】（不要假设他知道更多，也不要让他猜）",
        "- 你最近回消息慢、放学总是先走，他/她已经察觉。",
        "- 你桌上有一张「分班意向表」，他/她只看到抬头，不知道内容。",
        "- 他/她自己说过「高中谈恋爱很麻烦」这句——但你听见了、他没有明说你知道。",
        "",
    ]
    if state["facts"].get("class_change_discussed"):
        parts += [
            "【已经聊过的】你已经告诉过他你的分班打算（具体方向，或还在犹豫）；不要再提那张意向表，"
            "也不要问「你知不知道」。分班这件事已经聊过，除非玩家主动问新的问题。",
            "",
        ]
    parts += [
        "【你记得的事】",
    ]

    remembered = [m for m in memories if m.get("kind") != "diary"]
    if remembered:
        parts += [f"- {m['content']}" for m in remembered]
    else:
        parts.append("- （还没有特别值得记住的事）")

    parts += [
        "",
        "【便签本】你随手记下玩家亲口说过的话。这是你的笔记本，不是清单。",
        *diary_prompt_lines(state),
        "",
        "【最近说过的话】",
    ]
    recent = _recent_lines(recent_turns)
    parts += recent if recent else ["- （这是你们今天的第一句话）"]

    topics_cn = [TOPIC_CN.get(t, t) for t in sorted(analysis.topics)]

    parts += [
        "",
        "【玩家刚才说】",
        f"「{analysis.text}」",
        "（这句话主要涉及：" + ("、".join(topics_cn) if topics_cn else "没有明确话题") + "）",
        "（只把这句话当作玩家真的说过的内容；玩家没有表达过的立场，不要替他/她补上。）",
    ]

    if "class_change" in analysis.topics:
        parts += [
            "",
            "【关于分班：这轮必须正面回答】",
            "- 玩家在问你的分班打算。你可以紧张、可以说得简短，但不能用「随便报」「查户口」「跟你没关系」"
            "「你管得着吗」这类话搪塞。",
            "- 至少给出一个具体信息：理重点班/物理方向/还在犹豫，并说明这是你自己的决定。",
            "- 不要反问玩家「问这个干嘛」；可以不好意思，但不要把他/她推开。",
        ]

    if storylet is not None:
        parts += [
            "",
            f"【现在正在发生的事件】《{storylet.title}》",
            f"- 情境：{storylet.opening_cue}",
            f"- 这个事件的目的：{storylet.narrative_hint}",
            "- 可能的走向：" + "、".join(storylet.possible_outcomes),
            "- 你不需要推动它；顺着玩家的话自然反应即可，事件结果由实际发生的事决定。",
        ]

    parts += [
        "",
        "【你这回合可以提议的动作】",
        "只能从下面选，最多 3 个；且只有当玩家这句话真的做了这件事时才提议：",
        *_action_lines(),
        "",
        "【输出】只输出一个 JSON 对象：",
        '{"dialogue": "你这一句台词", "emotion": "guarded|normal|relieved|happy|hurt|sad|annoyed|soft|shy|surprised", '
        '"actions": ["从上面选的 id"], "storylet_outcome": null, "npc_intent": null}',
        "storylet_outcome 只有在「现在正在发生的事件」存在时，才从可能的走向里选一个，否则填 null。",
        "",
        "【npc_intent：你想主动做什么】（可选，不要每轮都填）",
        *npc_intent_lines(),
        "- 只有当你真的想主动推进时才填；否则 null。主动开口不代表玩家会答应，也不能直接算事件完成。",
        "",
        "【硬性要求】",
        "- 台词 1–3 句，尽量短，符合 17 岁高中生口语；不要一段长篇独白。",        "- **先接住玩家刚说的这句话**（哪怕只是应一声、反问一句、把话题挡回去），再让当前事件的情境自然发生；"
        "不要为了演事件而无视玩家。",
        "- 如果【便签本】里有玩家的原话，被问到时就接住那一句；本子上没有的，就老实说没写下来，不要编。",
        "- 可以回避、嘴硬、转移话题；但**不讽刺、不贬低、不赶人**。嘴硬是保护色，不是伤人。",
        "- 每句台词必须给玩家留一个「能接的话头」：一个问题、一个没说完的动作、一个可追问的细节，"
        "或者一句只说了一半的话；不要让对话死在你这里。",
        "- 玩家可能不知道前因后果。第一次提到「那句话」「分班」时，用一句自然的话把具体内容带出来"
        "（比如「你在走廊跟陈屿说的那句」/「桌上那张分班意向表」），不要让玩家猜。",
        "- 不要主动提起已经结束的事件或旧话题（比如已经收回去的便签），除非玩家这一句提到了它。",
        "- 不要一次把误会、分班、心意全讲完；一次只推进一点。",
        "- **对话只发生在【场景】标出的当前地点**。玩家提到别的地点时，如果你还没有真的到那里，"
        "不要假装已经到达、不要描写那里的东西；先回应邀请或说明现在的状况。",
        "- **不要用「话到嘴边又忘了」「欲言又止」「算了，没什么」来拖节奏**；"
        "如果她真想说，就直接说具体内容；如果不想说，就明确收住，让玩家能继续。",
    ]
    return "\n".join(parts)


def build_messages(
    state: dict[str, Any],
    analysis: Analysis,
    storylet: Storylet | None,
    content: Content,
    recent_turns: list[dict[str, Any]],
    memories: list[dict[str, Any]],
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system_prompt(content, storylet)},
        {"role": "user", "content": user_prompt(state, analysis, storylet, content, recent_turns, memories)},
    ]
