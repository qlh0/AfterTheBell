"""M0 角色 Agent：模板对白（不联网）。

它只做三件事，与 M1 的 LLM 版保持同一接口：
1. 说一句符合她此刻状态的话；
2. 给出结构化的动作提议（由 actions.py 校验后提交）；
3. 给出事件结果提议（由 storylet_resolution.py 校验后提交）。

台词是占位性质：M0 的目标是让规则闭环可玩、可测，而不是让对白以假乱真。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .. import game_state as gs
from ..narrative.storylets import Storylet
from ..rules.meaningful_turn import Analysis, primary_topic
from ..rules.outcome_rules import default_outcome


@dataclass
class AgentReply:
    dialogue: str
    emotion: str = "guarded"
    actions: list[str] = field(default_factory=list)
    storylet_outcome: str | None = None
    source: str = "mock"
    beat: str | None = None  # 可选的舞台提示（先于对白显示）
    # LLM 指标（mock 路径保持 0）
    model: str = ""
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str = ""
    notes: list[str] = field(default_factory=list)


TOPIC_LINES: dict[str, list[str]] = {
    "controlling": [
        "「你先别急着替我安排。」她把话截住，「我自己会想。」",
        "「你这样说，我反而更不想聊这个了。」",
        "「……我知道你是好意。」她顿了顿，「但这件事我想自己定。」",
    ],
    "romance": [
        "她愣了一下，随即低头去翻书页：「你、你突然说这个干嘛。」",
        "「别开玩笑。」她声音小下去，「这种话，我会当真的。」",
        "「……我不知道。」她没有笑，「你给我点时间，行吗？」",
    ],
    "misunderstanding": [
        "「你说的是哪句？」她抬眼看你，又很快移开，「我不记得了。」",
        "「那天的话，我听见了。」她说得很慢，「你不用解释，我就是……有点在意。」",
        "「算了。」她把书合上，「反正你也不是那个意思，对吧？」",
    ],
    "class_change": [
        "「表我还没交。」她用手压住那张纸，「我想报理重点班，就这样。」",
        "「分不分班，又不是我说了算。」她嘴上这么说，手指却在桌沿敲了两下。",
        "「你要是觉得我考不上，可以直接说。」",
    ],
    "distance": [
        "「最近？」她想了想，「可能是有点忙吧。」",
        "「我没有躲你。」她说得太快了，自己先停住。",
        "「你终于发现啦。」她笑了一下，不太像笑。",
        "「以前不都这样吗。」她把手机屏幕扣下去。",
    ],
    "chenyu": [
        "「陈屿啊。」她拖长了音，「他跟你说了什么？」",
        "「你们男生之间的事，我不掺和。」",
        "「他最近话是有点多。」",
    ],
    "apology": [
        "「你道什么歉啊。」她别过脸，「又不是你的错。」",
        "「……嗯。」她应了一声，没再说别的。",
        "「好啦，知道了。」她把声音放软，「别一直站着。」",
    ],
    "care": [
        "「我没事。」她说完，还是把杯子往你那边推了推。",
        "「你先顾好你自己吧。」嘴上这么说，神色松了一点。",
        "「谢谢。」她小声说，像怕被别人听见。",
    ],
    "leave": [
        "「哦，那你先走吧。」她低头收拾东西，没看你。",
        "「明天见。」她把书包背上，站在座位边没动。",
        "「路上小心。」",
    ],
    "smalltalk": [
        "「今天值日表又贴错了。」她吐槽了一句，语气跟以前一样。",
        "「作业你写完没？」她伸手来抽你的本子。",
        "「食堂今天的汤太咸了。」她皱着眉，认真得像在说一件大事。",
        "「你看窗外，云被吹散了。」她把下巴搁在手臂上。",
    ],
}

# 每个事件按「可能结果」准备台词：结果由玩家本回合真实说了什么决定。
STORYLET_LINES: dict[str, dict[str, list[str]]] = {
    "old_note": {
        "nostalgia_shared": [
            "「这个你还记得吗。」她把便签摊开一点，「去年秋天你塞我书里的，字丑得要命。」",
            "「我留着的。」她说完才意识到什么，飞快补了一句，「随便塞的，不算什么。」",
        ],
        "distance_kept": [
            "「没什么。」她把便签折回去，「旧东西了。」",
        ],
        "topic_avoided": [
            "「你别看。」她把手压在纸上，耳朵有点红。",
        ],
    },
    "direct_question": {
        "admitted_distance": [
            "「……我最近，是不太想说话。」她盯着桌角，「不是你的问题，是我自己的。」",
            "「你非要问的话。」她吸了口气，「我就是有点，不知道该用什么表情对你。」",
        ],
        "partial_truth": [
            "「也不全是因为那个。」她话到一半又停住，「算了，没事。」",
        ],
        "deflected": [
            "「你想多了。」她说完，自己先移开了视线。",
        ],
    },
    "chenyu_hint": {
        "hint_received": [
            "「他那天问我，你有没有跟我说什么。」她抬眼看你，「我说没有。」",
            "「陈屿让我别老是一个人憋着。」她笑了一下，「他话真多。」",
        ],
        "suspicion_raised": [
            "「你跟陈屿很熟啊。」她说完自己先皱了下眉。",
        ],
        "topic_dropped": [
            "「他也就是随口一句。」她把书合上，「你别多想。」",
        ],
    },
    "late_explanation": {
        "clarified": [
            "「……原来是这样。」她把手从桌沿上拿开，「我可能，想岔了。」",
            "「你早说啊。」她声音有点哑，「我这几天都在瞎想什么。」",
        ],
        "partially_clarified": [
            "「我听见的好像不是这个意思。」她没完全信，但也没再回避。",
        ],
        "worse": [
            "「你看，你现在也是这个口气。」她把脸别过去，「我不想听了。」",
        ],
    },
    "class_choice": {
        "discussed_respectfully": [
            "「我想试试。」她的手指点在纸上，「考不上就考不上，但我得先自己去考。」",
            "「你这么说……」她顿了一下，「我反而有点想认真准备了。」",
        ],
        "conflict_emerged": [
            "「这是我的事。」她把纸抽回去，「你凭什么替我决定？」",
        ],
        "topic_avoided": [
            "「这个啊……」她把纸往书里一夹，「以后再说吧。」",
        ],
    },
    "walk_home": {
        "walked_together": [
            "「顺路。」她先往前走了两步，又放慢了一点。",
            "「走快点啦。」她回头催你，语气跟以前一样。",
        ],
        "walked_apart": [
            "「哦，那你先走吧。」她站在路灯下没动，等你走出几步才转身。",
        ],
        "declined": [
            "「不用了。」她把书包带往上提了提，「我自己走。」",
        ],
    },
}

FINALE_LINES: dict[str, list[str]] = {
    "romance": [
        "「……嗯。」她低着头，耳朵红了，「那你可别后悔。」",
        "「我本来想等考完再说的。」她抬起头，眼睛亮亮的，「现在说也不算晚吧。」",
    ],
    "friends": [
        "「就先这样吧。」她笑了一下，很轻，「下学期还在一个学校呢，急什么。」",
        "「谢谢你今天留下来。」她把书包背好，「朋友也是要挑的，知道吧。」",
    ],
    "missed": [
        "「那我走了。」她说完转身，没有再回头。",
        "「你也早点回去吧。」她挥了挥手，隔着几步远，看不清表情。",
    ],
}

FINALE_WAIT_LINES = [
    "她没接话，只是把书包带又捏紧了一点，像在等你把话说完。",
    "「……嗯。」她应了一声，没有要走的意思。",
    "她抬头看了你一眼，又低下去，把没拉好的拉链拉上了。",
]

FALLBACK_LINES: dict[str, list[str]] = {
    "guarded": ["她没接话，只是把书页翻过去又翻回来。"],
    "normal": ["「嗯。」她应了一声，视线落在桌面。"],
    "relieved": ["她像是松了口气，肩膀垮下来一点。"],
    "happy": ["她弯了弯眼睛，没说话。"],
    "soft": ["她看着你，眼神比刚才软。"],
    "hurt": ["她抿着嘴，把椅子往后拉开了一点。"],
    "sad": ["她低下头，头发挡住了半张脸。"],
    "annoyed": ["她皱了下眉，没看你。"],
}

# 事件进行中玩家突然转向「心意」时，先给一个即时反应，再接事件台词。
_INTERRUPT_ROMANCE = "她手里的事停了一下。"


def _line_for(pool: list[str], index: int, fallback_emotion: str) -> str:
    if pool:
        return pool[index % len(pool)]
    fb = FALLBACK_LINES.get(fallback_emotion, FALLBACK_LINES["normal"])
    return fb[index % len(fb)]


def reply(
    state: dict[str, Any],
    analysis: Analysis,
    storylet: Storylet | None,
    expected_ending: str | None = None,
) -> AgentReply:
    idx = state["turn_index"]
    emotion = gs.derive_emotion(state)

    if storylet is not None and storylet.kind == "finale":
        # 她是否给出最后的答复，取决于玩家这一句是否真的把话推进了一步
        if not analysis.is_meaningful:
            return AgentReply(
                dialogue=FINALE_WAIT_LINES[idx % len(FINALE_WAIT_LINES)],
                emotion=emotion,
                actions=analysis.actions,
                storylet_outcome=None,
                source="mock",
            )
        pool = FINALE_LINES.get(expected_ending or "missed", FINALE_LINES["missed"])
        return AgentReply(
            dialogue=_line_for(pool, idx, emotion),
            emotion=emotion,
            actions=analysis.actions,
            storylet_outcome=None,
            source="mock",
        )

    if storylet is not None:
        outcome = default_outcome(storylet, analysis)
        buckets = STORYLET_LINES.get(storylet.id, {})
        pool = buckets.get(outcome or "") or buckets.get("topic_avoided") or []
        line = _line_for(pool, idx, emotion)
        beat = None
        if "romance" in analysis.topics and storylet.id != "finale":
            beat = _INTERRUPT_ROMANCE
        return AgentReply(
            dialogue=line,
            emotion=emotion,
            actions=analysis.actions,
            storylet_outcome=outcome,
            source="mock",
            beat=beat,
        )

    topic = primary_topic(analysis)
    pool = TOPIC_LINES.get(topic) or TOPIC_LINES["smalltalk"]
    return AgentReply(
        dialogue=_line_for(pool, idx, emotion),
        emotion=emotion,
        actions=analysis.actions,
        storylet_outcome=None,
        source="mock",
    )
