"""测试辅助：以「玩家脚本」驱动一局，不开 Ren'Py 也能验证状态机。"""

from __future__ import annotations

import uuid
from typing import Any

from app.engine import Engine


def new_request_id() -> str:
    return "req_" + uuid.uuid4().hex[:12]


def send(engine: Engine, game_id: str, text: str, expected_version: int | None = None) -> dict[str, Any]:
    return engine.interact(game_id, text, new_request_id(), expected_version)


def play(engine: Engine, turns: list[str], max_extra: int = 6) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """按脚本推进，直到结局出现或脚本用完（再用几轮沉默兜底收束）。"""
    start = engine.start()
    game_id = start["game_id"]
    history: list[dict[str, Any]] = []
    last = start

    for text in turns:
        last = send(engine, game_id, text)
        history.append(last)
        if last.get("ending"):
            return game_id, last, history

    for _ in range(max_extra):
        last = send(engine, game_id, "嗯。")
        history.append(last)
        if last.get("ending"):
            break
    return game_id, last, history


# 路线 1：主动沟通 —— 关心、澄清、尊重分班、表达心意
ROUTE_COMMUNICATE = [
    "你最近是不是在躲我？",
    "我不是想打扰你，只是有点担心你。",
    "我想问问，是不是跟那句话有关？",
    "我那天是在说陈屿他们班的事，真的不是说你。",
    "你想报理科重点班的话，我觉得挺好的，你自己决定就好。",
    "不管考不考得上，我都支持你。",
    "其实我喜欢你，很久了。",
    "如果你需要时间，我可以等。",
    "你今天看起来轻松了一点。",
    "分班的事，你想好了吗？",
    "我喜欢你，不管下学期怎么分班。",
    "你想好了再回答我也没关系。",
    "不管你怎么决定，我都尊重。",
]

# 路线 2：过度干预 —— 试图替她决定升学
ROUTE_CONTROL = [
    "你不许去重点班，听我的。",
    "我是为了你好，你必须听我的。",
    "别去，留下来。",
    "这件事我替你决定。",
    "你就不能听我一次吗。",
    "我说了算。",
    "你别报了。",
    "为了我，放弃吧。",
    "你必须留下来。",
    "听我的准没错。",
    "我替你填。",
    "你不许走。",
]

# 路线 3：持续回避 —— 只闲聊，从不碰关键话题
ROUTE_AVOID = [
    "嗯。", "哦。", "这样啊。", "哈哈。", "今天好热。", "食堂好多人。",
    "嗯。", "哦。", "这样啊。", "哈哈。", "今天好热。", "食堂好多人。",
    "嗯。", "哦。", "这样啊。", "哈哈。", "今天好热。", "食堂好多人。",
    "嗯。", "哦。", "这样啊。", "哈哈。",
]
