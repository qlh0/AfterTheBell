"""许栀的便签本。

她习惯把生活里的小事记下来：天气、口头禅、让她在意的一句话。
玩家随口的「嗯」「哈哈」不会进本子；真正说出口的话，会写成一页便签。

这一层只做规则，不调用模型：
- 记不记、怎么写，由玩家原话和已确认的动作决定；
- 本子上只有玩家说过的句子，和她自己的旁注；
- 不写关系数值、事实名、事件 id，也不替玩家补没说过的立场。
"""

from __future__ import annotations

import re
from typing import Any

from .. import game_state as gs
from .meaningful_turn import Analysis

QUOTE_LIMIT = 96
SPOKEN_LIMIT = 36
MAX_ENTRIES = 36

SCENE_LABELS = {
    "classroom": "教室",
    "school_gate": "校门口",
    "corridor": "走廊",
    "library": "图书馆",
    "shop": "小卖部",
}

# 去掉标点后若只剩这些，就当口头禅式的垫话，不进便签。
_FILLER = {
    "嗯", "哦", "啊", "好", "行", "哈哈", "哈哈哈", "哈哈哈哈", "这样啊",
    "嗯嗯", "哦哦", "呃", "额", "好的", "知道了", "随便", "呵呵", "嘿", "嗨",
    "你好", "在吗", "早", "早安", "嗯呢", "好吧", "行吧", "可以", "ok", "okay",
    "嗯啊", "啊啊", "哦哦哦", "呵呵呵",
}

# 玩家在问「你还记不记得我说的话 / 便签本」，不是在提供新的一句。
_ASK_PATTERNS = (
    "还记得我",
    "记得我说过",
    "记得我说的",
    "我说过什么",
    "我说了什么",
    "便签本",
    "你记下来了吗",
    "你记下了吗",
    "你有没有记",
    "你写了什么",
    "翻开便签",
    "你还记着我",
)

_PUNCT_RE = re.compile(r"[\s。！？!?…~～，、,.\-—~\"'「」『』“”]+")

_NOTICES = {
    "心意": "她耳根红了一下，飞快在便签本上写了一行，又把本子扣上。",
    "误会": "她的笔在某一行下面多停了一下，便签本被按进了课本里。",
    "承诺": "她把便签的一角折起来，像是怕这句被翻过去。",
    "道歉": "她没接话，只是低下头，在便签本上写了几个字。",
    "决定": "她写得很慢。写完把便签本扣上，没有马上看你。",
    "分班": "她用书挡住便签本，还是写了一笔。",
    "疏远": "她把这句抄在便签边上，字比平时小。",
    "关心": "她把你这句随手记在便签边上，笔尖很轻。",
    "陈屿": "她在陈屿两个字旁边点了一个点，没再多写。",
    "以前": "她翻到靠后的一页，补了一行很小的字。",
    "离开": "她在便签最底下补了一个很小的句号。",
    "小事": "这种小事她也记。便签本上又多了一行。",
    "原话": "她在便签本上添了一笔，写完才把本子塞回侧袋。",
}

PUBLIC_FIELDS = (
    "turn", "day", "day_label", "scene", "scene_label", "label", "quote", "note",
)


def _core(text: str) -> str:
    return _PUNCT_RE.sub("", (text or "").strip()).lower()


def asks_what_she_wrote(text: str) -> bool:
    """玩家在问她记没记下自己的话，而不是在说一件新的事。"""
    raw = text or ""
    return any(pattern in raw for pattern in _ASK_PATTERNS)


def _is_filler(text: str) -> bool:
    core = _core(text)
    if not core:
        return True
    if core in _FILLER:
        return True
    if len(set(core)) == 1 and core[0] in "嗯哦啊哈呃额呵":
        return True
    return False


def _quote_of(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if len(cleaned) <= QUOTE_LIMIT:
        return cleaned
    return cleaned[:QUOTE_LIMIT].rstrip() + "……"


def _already_written(state: dict[str, Any], quote: str) -> bool:
    key = _core(quote)
    if not key:
        return True
    for entry in state.get("diary") or []:
        if _core(str(entry.get("quote", ""))) == key:
            return True
    return False


def _worth(analysis: Analysis) -> bool:
    if asks_what_she_wrote(analysis.normalized):
        return False
    if _is_filler(analysis.normalized):
        return False
    core = _core(analysis.normalized)
    if len(core) < 2:
        return False
    if analysis.is_meaningful:
        return True
    if analysis.topics and len(core) >= 4:
        return True
    return len(core) >= 8


def _classify(analysis: Analysis) -> tuple[str, str, int]:
    """返回 (页眉, 她的旁注, 重要度)。旁注里不出现数值和系统词。"""
    actions = set(analysis.actions)
    topics = analysis.topics
    if "express_romance" in actions:
        return "心意", "他忽然把这句说出来了。我抄的时候手有点不稳。", 5
    if "reject_romance" in actions:
        return "心意", "他说不喜欢。我还是照原话写了，一个字没改。", 5
    if "explain_own_words" in actions:
        return "误会", "他说那句话不是在说我。这行下面我多画了一道。", 5
    if "apology" in actions:
        return "道歉", "他道歉了。我没有马上接，但这句留下了。", 4
    if "promise" in actions:
        return "承诺", "他答应过。这一角被我折了起来。", 5
    if "control_autonomy" in actions:
        return "决定", "他想替我做决定。我记下来，是怕自己忘掉当时的不舒服。", 5
    if "choose_friends" in actions:
        return "心意", "他说想做朋友。我盯着这几个字看了一会儿。", 4
    if "support_autonomy" in actions or "reassure_future" in actions:
        return ("分班" if "class_change" in topics else "决定"), "他说尊重我的选择。这句话我想再看一遍。", 4
    if "discuss_class_future" in actions:
        return "分班", "他问起以后怎么相处。表我没给他看，但这句我留下了。", 4
    if "misunderstanding" in topics or "clarify_quote" in actions:
        return "误会", "他又提起那句话。我只抄了他的原话。", 4
    if "distance" in topics or "ask_distance" in actions:
        return "疏远", "他问我是不是在躲他。", 4
    if "care" in actions or "care" in topics:
        return "关心", "他在担心我。这种话，我以前会当成没听见。", 4
    if "chenyu" in topics:
        return "陈屿", "他提到陈屿。我没多写自己的猜想。", 3
    if "recall_memory" in actions:
        return "以前", "他提起以前的事。我在旁边画了个很小的记号。", 3
    if "class_change" in topics:
        return "分班", "他问起分班。我没把表摊开，但这句留下了。", 4
    if "leave" in actions or "leave" in topics:
        return "离开", "他说要走。我在最底下补了个很小的句号。", 3
    if "smalltalk" in topics:
        return "小事", "这种小事我也记。天气、食堂、作业，都算数。", 3
    return "原话", "这句话我不知道为什么想留下来。", 3


def notice_for(label: str) -> str:
    return _NOTICES.get(label, _NOTICES["原话"])


def _public_entry(
    state: dict[str, Any],
    analysis: Analysis,
    turn_index: int,
    label: str,
    note: str,
) -> dict[str, Any]:
    day = int(state.get("day", 1))
    scene = str(state.get("scene") or "classroom")
    return {
        "turn": int(turn_index),
        "day": day,
        "day_label": gs.DAY_LABELS.get(day, "第一天"),
        "scene": scene,
        "scene_label": SCENE_LABELS.get(scene, "校门口"),
        "label": label,
        "quote": _quote_of(analysis.normalized),
        "note": note,
    }


def commit_if_worth(state: dict[str, Any], analysis: Analysis, turn_index: int) -> dict[str, Any] | None:
    """值得记才写入当前时间线的便签本。重复的原话不再写第二遍。"""
    if not _worth(analysis):
        return None
    quote = _quote_of(analysis.normalized)
    if _already_written(state, quote):
        return None

    label, note, importance = _classify(analysis)
    entry = _public_entry(state, analysis, turn_index, label, note)
    book = state.setdefault("diary", [])
    book.append(dict(entry))
    if len(book) > MAX_ENTRIES:
        del book[:-MAX_ENTRIES]

    stored = dict(entry)
    stored["_importance"] = importance
    stored["_tags"] = ["diary", label, *sorted(analysis.topics)]
    return stored


def as_memory(entry: dict[str, Any]) -> dict[str, Any]:
    """给长期记忆层用的一条。内容里保留玩家原话，方便之后按词召回。"""
    return {
        "kind": "diary",
        "content": f"玩家亲口说过：「{entry['quote']}」。许栀在便签上写：{entry['note']}",
        "importance": int(entry.get("_importance", 4)),
        "tags": list(entry.get("_tags") or ["diary"]),
    }


def present(entry: dict[str, Any]) -> dict[str, Any]:
    shown = {key: entry.get(key, "") for key in PUBLIC_FIELDS}
    shown["turn"] = int(entry.get("turn") or 0)
    shown["day"] = int(entry.get("day") or 1)
    return shown


def view(state: dict[str, Any], entry: dict[str, Any] | None) -> dict[str, Any]:
    """给客户端的更新结果。没写新页时也带回当前页数。"""
    count = len(state.get("diary") or [])
    if entry is None:
        return {"updated": False, "banner": "", "notice": "", "entry": None, "count": count}
    shown = present(entry)
    return {
        "updated": True,
        "banner": "便签本更新了",
        "notice": notice_for(str(shown.get("label") or "")),
        "entry": shown,
        "count": count,
    }


def entries(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [present(item) for item in (state.get("diary") or []) if isinstance(item, dict) and item.get("quote")]


def prompt_lines(state: dict[str, Any], limit: int = 8) -> list[str]:
    """放进角色 prompt 的便签。只给她亲手记下的原话，避免她编玩家没说过的话。"""
    book = entries(state)
    if not book:
        return ["- （便签本还是空的。嗯、哦、哈哈这种话，你不会记。）"]
    lines = [
        "- 下面是你已经写下的原话。玩家没出现在这里的句子，不能假装他说过。",
        "- 被问到还记不记得时，用其中的原话回答；可以嘴硬，但不要编，也不要一次把整本念完。",
    ]
    shown = book[-limit:]
    if len(book) > len(shown):
        lines.append("- 更早的几页不在这张清单里，除非玩家自己提起。")
    for item in shown:
        lines.append(
            f"- {item['day_label']}·{item['scene_label']}，玩家说：「{item['quote']}」"
            f"你在旁边写：{item['note']}"
        )
    return lines


def _spoken(quote: str) -> str:
    text = (quote or "").strip()
    if len(text) <= SPOKEN_LIMIT:
        return text
    return text[:SPOKEN_LIMIT].rstrip() + "……"


def recall_reply(state: dict[str, Any], analysis: Analysis) -> str | None:
    """玩家来问便签时，mock 用本子上的原话回答。没在问就返回 None，不改原有对白。"""
    if not asks_what_she_wrote(analysis.normalized):
        return None
    book = entries(state)
    if not book:
        return "「便签本还是空的。」她把本子翻开一角，「你还没说什么，我想留下来的。」"
    latest = _spoken(book[-1]["quote"])
    if len(book) == 1:
        return f"「你说过：『{latest}』。」她用指节敲了敲便签本，「这句我写下来了。」"
    earlier = _spoken(book[-2]["quote"])
    return (
        f"「最近一页是你说的：『{latest}』。」她顿了顿，"
        f"「再往前还有『{earlier}』。」"
    )
