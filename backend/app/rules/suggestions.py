"""给玩家的「可以这么说」提示。

不是选项分支，也不是强制剧情：只是把当前还能推进的话题，写成几句玩家可以
直接发送、也可以改几个字的句子。它解决的是「不知道下一句该说什么」，
不改变"自由输入"的性质。

规则生成，不调用模型；同一状态下结果稳定，便于测试。
"""

from __future__ import annotations

from typing import Any

from .. import game_state as gs
from ..narrative.storylets import Storylet

MAX_SUGGESTIONS = 4


def _item(sid: str, label: str, text: str) -> dict[str, str]:
    return {"id": sid, "label": label, "text": text}


def suggestions(
    state: dict[str, Any], storylet: Storylet | None = None
) -> list[dict[str, str]]:
    facts = state["facts"]
    rel = state["relationship"]
    items: list[dict[str, str]] = []

    # 事件进行中：优先给能推进/收尾这个事件的句子
    if storylet is not None:
        sid = storylet.id
        if sid == "late_explanation":
            items += [
                _item("explain", "解释那句", "我那天真的不是在说你，是在说陈屿他们班的事。"),
                _item("listen", "先听她说", "你先说，我听着。你想说多少都行。"),
            ]
        elif sid == "class_choice":
            items += [
                _item("support", "支持她", "报不报是你自己的事，我支持你的决定。"),
                _item("worry", "说出担心", "我其实是有点怕，分班以后就不能这样一起走了。"),
            ]
        elif sid == "walk_home":
            items += [
                _item("walk", "一起走", "一起走吧，正好顺路。"),
                _item("ask", "问她想法", "你最近是不是有什么事没跟我说？"),
            ]
        elif sid == "direct_question":
            items += [
                _item("ask", "追问", "我不是想逼你，就是想知道你最近怎么了。"),
                _item("wait", "不逼她", "你不想说也没关系，我陪你坐一会儿。"),
            ]
        elif sid == "chenyu_hint":
            items += [
                _item("chenyu", "问陈屿", "陈屿是不是跟你说什么了？"),
                _item("self", "说自己", "我不太会安慰人，但我在听。"),
            ]
        elif sid == "old_note":
            items += [
                _item("note", "接住旧事", "那张便签你还留着啊。"),
                _item("care", "关心她", "你最近是不是遇到什么事了？"),
            ]
        elif sid == "shared_memory":
            items += [
                _item("remember", "接住回忆", "我记得那次。你当时还笑我。"),
                _item("own_version", "说说你记得的", "我印象里的版本好像跟你不太一样。"),
                _item("care", "关心她", "你怎么突然想起这个了？"),
            ]
        elif sid == "unfinished_conversation":
            items += [
                _item("feelings", "说出感受", "我不想再这样各想各的了，我们能不能说开？"),
                _item("apology", "道歉", "刚才是我不好，我不该那样说。"),
                _item("listen", "先听她说", "你先说，我听着。"),
            ]
        elif sid == "library_study":
            items += [
                _item("study", "一起学习", "这道题你会吗？我们一起看看。"),
                _item("ask", "问她最近", "你最近是不是有什么心事？在这里说也没关系。"),
                _item("leave", "先走", "要不今天先到这里？"),
            ]
        elif sid == "corridor_chat":
            items += [
                _item("talk", "说点什么", "其实我刚才在教室里就想跟你说。"),
                _item("ask", "问她最近", "你最近是不是在躲我？"),
                _item("leave", "先走", "算了，先下楼吧。"),
            ]
        elif sid == "shop_trip":
            items += [
                _item("buy", "帮她挑", "你想喝什么？我请你。"),
                _item("share", "买两瓶", "买两瓶一样的吧，路上喝。"),
                _item("leave", "先走", "我还有点事，先走了。"),
            ]
        elif sid == "school_gate_finale":
            items += [
                _item("confess", "说出心意", "我喜欢你，不管下学期分不分班。"),
                _item("friends", "先说做朋友", "不管怎样，我们还是朋友，对吧？"),
                _item("wait", "给她时间", "你不用现在回答我，我等你。"),
            ]

    # 没有事件时：先给当前场景可去的日常活动，再给「还没推进的目标」
    if not items:
        used = set(state.get("used_storylets") or [])
        scene = state.get("scene")
        if scene == "classroom":
            if "library_study" not in used:
                items.append(_item("library", "去图书馆", "放学后要不要一起去图书馆学习？"))
            if "corridor_chat" not in used:
                items.append(_item("corridor", "走廊聊两句", "陪我去走廊站一会儿吧。"))
        elif scene == "school_gate" and "shop_trip" not in used:
            items.append(_item("shop", "去小卖部", "一起去小卖部买点东西吧。"))

        if not facts["player_asked_distance"]:
            items.append(_item("ask_distance", "问她怎么了", "你最近是不是在躲我？"))
        if facts["misunderstanding_discussed"] and not facts["misunderstanding_resolved"]:
            items.append(_item("clarify", "澄清误会", "我说的不是你，那天是在说陈屿他们班。"))
        if not facts["class_change_discussed"]:
            items.append(_item("class", "聊分班", "分班的事，你是怎么想的？"))
        if rel["respect_for_autonomy"] < 45:
            items.append(_item("soften", "放软态度", "对不起，刚才是我太急了。你想怎么办，我都尊重。"))
        if rel["trust"] >= 55 and not facts["player_expressed_romance"]:
            items.append(_item("heart", "试探心意", "如果我告诉你，我有点喜欢你，你会怎么想？"))
        if gs.near_end(state):
            items.append(_item("close", "把话说开", "今天我们能不能把话说明白？我不想就这么走。"))

    # 兜底：至少给两句日常，保证玩家永远不会面对空白
    if len(items) < 2:
        items.append(_item("care", "关心她", "你今天看起来有点累，还好吗？"))
    if len(items) < 2:
        items.append(_item("smalltalk", "聊点日常", "晚上还有作业吗？"))

    # 去重 + 截断
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for item in items:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        unique.append(item)
    return unique[:MAX_SUGGESTIONS]
