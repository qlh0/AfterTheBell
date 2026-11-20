"""轻量的「第二天计划」：只把玩家意图转成开场种子和提示偏好。

这里不提交任何关系值、事实或结局；真正的结果仍由第二天的对话和规则决定。
"""

from __future__ import annotations

from typing import Any

MAX_PLAN_CHARS = 200
FREE_PLAN = "顺其自然。"

# 顺序即主标签优先级：先解决没说完的话，再学习/日常/告白。
PLAN_TAGS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("clarify", ("说开", "解释", "道歉", "分班", "误会", "聊聊", "说清楚", "把话说")),
    ("study", ("图书馆", "学习", "复习", "题", "自习", "作业")),
    ("snack", ("小卖部", "零食", "饮料", "请她", "买")),
    ("confess", ("表白", "喜欢", "在一起", "告白", "心意")),
)

OPENINGS = {
    "clarify": "第二天放学后，你决定找个机会，把昨天没说完的话说清楚。",
    "study": "第二天放学后，你把练习册放在桌角，想着怎么开口约她去图书馆。",
    "snack": "第二天放学后，你想起她昨天在小卖部门口停了一下。",
    "confess": "第二天放学后，你反复想着，要不要把心意说出来。",
    "free": "第二天放学后，教室里只剩下你们两个。",
}


def normalize(text: str | None) -> str:
    value = (text or "").strip()
    if not value:
        return FREE_PLAN
    return value[:MAX_PLAN_CHARS]


def classify(text: str | None) -> list[str]:
    value = normalize(text)
    tags = [
        tag for tag, words in PLAN_TAGS
        if any(word in value for word in words)
    ]
    return tags or ["free"]


def opening_for(tags: list[str]) -> str:
    for tag in tags:
        if tag in OPENINGS:
            return OPENINGS[tag]
    return OPENINGS["free"]


def plan_payload(text: str | None) -> dict[str, Any]:
    value = normalize(text)
    tags = classify(value)
    return {
        "text": value,
        "tags": tags,
        "status": "consumed",
        "opening": opening_for(tags),
    }
