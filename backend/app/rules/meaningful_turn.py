"""把玩家自由文本解析成「意图 + 话题 + 候选动作」。

这一层是规则，不是理解：它决定
1. 这一回合算不算「有意义的互动」；
2. 玩家的话里提到了哪些话题（用于故事事件与状态提交）；
3. 玩家可能在做哪几类动作（动作白名单见 actions.py）。

M1 接 LLM 后，LLM 只负责「对白 + 动作提议」，这里的关键词规则继续作为
校验与兜底：LLM 提议的动作必须能在本回合文本里找到依据。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# 话题 → 关键词。命中即认为玩家在说这件事。
TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "distance": (
        "冷淡", "疏远", "躲", "不理", "不回", "消息", "回复", "怎么了", "最近",
        "生气", "怪你", "怪你", "不对劲", "不理我", "看不见", "不理人", "在躲",
    ),
    "misunderstanding": (
        "那句话", "误会", "听见", "听到", "听见了", "谈恋爱", "麻烦", "不是那个意思",
        "我没有那个意思", "澄清", "解释", "说清楚", "陈屿说", "你以为", "你误会",
    ),
    "class_change": (
        "分班", "重点班", "理科", "意向表", "那张表", "升学", "下学期", "分科", "名额",
        "考", "成绩", "重点",
    ),
    "romance": (
        "喜欢", "告白", "表白", "在一起", "交往", "女朋友", "谈恋爱", "心动",
        "想和你", "陪着你", "我等你", "约会",
    ),
    "chenyu": ("陈屿",),
    "care": ("担心", "还好吗", "累", "别难过", "陪你", "注意", "早点回", "多吃"),
    "apology": ("对不起", "抱歉", "是我不好", "我错了", "别生气"),
    "controlling": (
        "不许", "不准", "别去", "不要去", "不要报", "必须", "听我的", "我替你",
        "为了我", "你得", "一定要", "我说了算", "放弃", "不准报", "别报",
    ),
    "leave": ("走了", "回家", "先走", "拜拜", "再见", "我走了", "先回去了", "明天见"),
    "smalltalk": ("天气", "作业", "考试", "午饭", "食堂", "哈哈", "今天", "学校", "值日", "笔记"),
}

# 动作 → 触发它的关键词（用于从文本推出候选动作；顺序有意义）
ACTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "control_autonomy": TOPIC_KEYWORDS["controlling"],
    "explain_own_words": (
        "不是那个意思", "我是说", "我当时", "那句话是", "我说的是", "你别误会", "不是说你",
    ),
    "express_romance": TOPIC_KEYWORDS["romance"],
    "clarify_quote": ("那句话", "误会", "澄清", "解释", "听见", "听到", "说清楚"),
    "ask_distance": TOPIC_KEYWORDS["distance"],
    "ask_chenyu": TOPIC_KEYWORDS["chenyu"],
    "support_autonomy": (
        "你自己决定", "你自己想", "我支持", "你想去就去", "我陪你考", "尊重你",
        "你的选择", "我帮你一起", "不管怎样",
    ),
    "apology": TOPIC_KEYWORDS["apology"],
    "care": TOPIC_KEYWORDS["care"],
    "promise": ("我会", "答应你", "我保证", "一定", "我等你", "不会忘"),
    "leave": TOPIC_KEYWORDS["leave"],
    "small_talk": TOPIC_KEYWORDS["smalltalk"],
}

# 这些话题让一回合算「有效互动」（闲聊与道别不算推进剧情，但道别仍算有意图）
MEANINGFUL_TOPICS = {"distance", "misunderstanding", "class_change", "romance", "chenyu", "care", "apology", "controlling"}

QUESTION_MARKERS = ("?", "？", "吗", "呢", "怎么", "为什么", "什么", "是不是", "要不要")

_WS_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    text = text.strip()
    text = _WS_RE.sub(" ", text)
    return text


@dataclass
class Analysis:
    text: str
    normalized: str
    topics: set[str] = field(default_factory=set)
    actions: list[str] = field(default_factory=list)
    is_question: bool = False
    controlling: bool = False
    is_meaningful: bool = False
    meaningful_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "topics": sorted(self.topics),
            "actions": self.actions,
            "is_question": self.is_question,
            "controlling": self.controlling,
            "is_meaningful": self.is_meaningful,
            "meaningful_reason": self.meaningful_reason,
        }


def _hits(text: str, words: tuple[str, ...]) -> bool:
    return any(w in text for w in words)


def analyze(text: str) -> Analysis:
    norm = normalize(text)
    topics = {topic for topic, words in TOPIC_KEYWORDS.items() if _hits(norm, words)}
    is_question = _hits(norm, QUESTION_MARKERS)

    actions: list[str] = []
    for action, words in ACTION_KEYWORDS.items():
        if _hits(norm, words):
            actions.append(action)

    # 有话题但没匹配到具体动作时，按话题补一个最贴切的动作
    if not actions:
        if "distance" in topics:
            actions.append("ask_distance")
        elif "class_change" in topics:
            actions.append("support_autonomy")
        elif "misunderstanding" in topics:
            actions.append("clarify_quote")
        elif "romance" in topics:
            actions.append("express_romance")
        elif "care" in topics:
            actions.append("care")
        else:
            actions.append("small_talk")
    # 去重且保序
    actions = list(dict.fromkeys(actions))

    controlling = "controlling" in topics
    is_meaningful = False
    reason = ""
    if controlling:
        is_meaningful, reason = True, "玩家在替她做决定"
    elif topics & MEANINGFUL_TOPICS:
        is_meaningful, reason = True, "触及关键话题：" + "/".join(sorted(topics & MEANINGFUL_TOPICS))
    elif "leave" in topics:
        is_meaningful, reason = True, "玩家表达了离场意图"
    elif is_question and len(norm) >= 5:
        is_meaningful, reason = True, "玩家提出了问题"
    elif len(norm) >= 14:
        is_meaningful, reason = True, "玩家主动说了较长的一段话"
    else:
        is_meaningful, reason = False, "闲聊/短回应"

    return Analysis(
        text=text,
        normalized=norm,
        topics=topics,
        actions=actions,
        is_question=is_question,
        controlling=controlling,
        is_meaningful=is_meaningful,
        meaningful_reason=reason,
    )


def primary_topic(analysis: Analysis) -> str:
    """给 mock 对白选模板时用的「主要话题」优先级。"""
    priority = [
        "controlling", "romance", "misunderstanding", "class_change",
        "distance", "chenyu", "apology", "care", "leave", "smalltalk",
    ]
    for topic in priority:
        if topic in analysis.topics:
            return topic
    return "smalltalk"
