"""事件收尾：由「玩家实际说了什么」+「事件走向」决定状态提交。

M1 起，事件走向优先采用经过白名单校验的 LLM 提议（更贴合实际对白），
没有提议或提议非法时退回规则默认值。无论哪种，数值与事实的提交都在这里，
模型不能直接写状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .. import game_state as gs
from ..narrative.storylets import Storylet
from ..rules.meaningful_turn import Analysis
from .outcome_rules import default_outcome


@dataclass
class Resolution:
    outcome: str
    changes: list[dict[str, Any]] = field(default_factory=list)
    narration: list[str] = field(default_factory=list)
    memory: tuple[str, str, int, list[str]] | None = None  # (kind, content, importance, tags)


# 每个事件 × 每个可能走向的固定效果。
# rel: 关系数值增量；facts: 置为 True 的事实；narr: 舞台提示；mem: 记忆。
OUTCOMES: dict[str, dict[str, dict[str, Any]]] = {
    "old_note": {
        "nostalgia_shared": {
            "rel": {"trust": 2, "affection": 2},
            "narr": ["她盯着便签上的字看了一会儿，没忍住笑了一下，又很快压回去。"],
            "mem": ("episode", "旧便签：两人一起想起以前传纸条的日子。", 4, ["old_note", "history"]),
        },
        "distance_kept": {
            "rel": {"respect_for_autonomy": -1},
            "narr": ["她把便签收了回去，动作比刚才快。"],
            "mem": ("episode", "旧便签：玩家当时只顾着催她，气氛变冷了。", 2, ["old_note"]),
        },
        "topic_avoided": {
            "rel": {"affection": 1},
            "narr": ["她把便签塞回书里，换了个话题。"],
            "mem": ("episode", "旧便签：玩家没有接住她递出来的旧事。", 2, ["old_note"]),
        },
    },
    "direct_question": {
        "admitted_distance": {
            "rel": {"trust": 3, "affection": 1},
            "facts": ["distance_noticed"],
            "narr": ["她先低头把笔帽按了回去，才慢慢开口。"],
            "mem": ("episode", "玩家直接问她最近为什么冷淡，她承认了一点。", 5, ["distance"]),
        },
        "partial_truth": {
            "rel": {"trust": 1},
            "narr": ["她话到一半停住，像在衡量要不要说下去。"],
            "mem": ("episode", "她差点说出疏远的原因，又自己收住了。", 3, ["distance", "secret"]),
        },
        "deflected": {
            "rel": {"trust": -1},
            "narr": ["她把话推了回来，语气有点用力。"],
        },
    },
    "chenyu_hint": {
        "hint_received": {
            "rel": {"trust": 2},
            "facts": ["chenyu_hint_seen"],
            "narr": ["她停了停，像在斟酌该说多少。"],
            "mem": ("episode", "陈屿这条线提供了一点线索，但许栀显然不想多说。", 4, ["chenyu"]),
        },
        "suspicion_raised": {
            "rel": {"trust": -1},
            "narr": ["她说完自己先皱了下眉，好像也觉得没必要。"],
            "mem": ("episode", "提到陈屿时她有点在意，但没解释。", 3, ["chenyu", "jealousy"]),
        },
        "topic_dropped": {
            "rel": {},
            "narr": ["她把话题轻轻放下了。"],
            "mem": ("episode", "陈屿的线索没有被接住。", 2, ["chenyu"]),
        },
    },
    "late_explanation": {
        "clarified": {
            "rel": {"trust": 6, "affection": 4},
            "facts": ["misunderstanding_resolved", "misunderstanding_discussed"],
            "narr": ["她听完，很久没说话。", "然后她把放在桌沿的手收了回去。"],
            "mem": ("promise", "误会解开了：那句话是在说别人，不是嫌弃她。", 5, ["misunderstanding"]),
        },
        "partially_clarified": {
            "rel": {"trust": 2, "affection": 1},
            "facts": ["misunderstanding_discussed"],
            "narr": ["她听你把话说完，没有立刻回应。"],
            "mem": ("episode", "那句话被提起来了，但没有真正说开。", 3, ["misunderstanding"]),
        },
        "worse": {
            "rel": {"respect_for_autonomy": -5, "trust": -3},
            "narr": ["她把脸别过去，肩膀绷了一下。"],
            "mem": ("episode", "解释那句话的时候，玩家又替她做了决定，谈得更僵了。", 5, ["misunderstanding"]),
        },
    },
    "class_choice": {
        "discussed_respectfully": {
            "rel": {"respect_for_autonomy": 4, "trust": 2},
            "facts": ["class_change_discussed"],
            "narr": ["她说得很慢，一边说一边看你的反应。"],
            "mem": ("episode", "两人认真谈过分班：她想去理重点班，玩家没有替她做决定。", 5, ["class_change", "respect"]),
        },
        "conflict_emerged": {
            "rel": {"respect_for_autonomy": -6, "trust": -2},
            "facts": ["class_change_discussed", "player_controlling"],
            "narr": ["她把那张纸收进抽屉，动作重了一点。"],
            "mem": ("conflict", "玩家想替她决定要不要报重点班，她明确反感。", 5, ["class_change", "autonomy"]),
        },
        "topic_avoided": {
            "rel": {"respect_for_autonomy": 1},
            "narr": ["她把纸往书里一夹，把话题放下了。"],
            "mem": ("episode", "分班的话题被她推到了以后。", 2, ["class_change"]),
        },
    },
    "walk_home": {
        "walked_and_talked": {
            "rel": {"trust": 4, "affection": 4},
            "facts": ["walk_home_done"],
            "narr": ["你们并肩走了一段，聊到了分班、也聊到了以后。", "路灯一盏一盏亮起来，她的步子比平时慢。"],
            "mem": ("episode", "两人一起走了一段，也第一次认真聊了以后。", 5, ["walk_home"]),
        },
        "walked_together": {
            "rel": {"trust": 3, "affection": 3},
            "facts": ["walk_home_done"],
            "narr": ["你们并肩走了一段，谁都没先提分班的事。", "路灯一盏一盏亮起来，她的步子比平时慢。"],
            "mem": ("episode", "两人一起走了一段放学路，气氛缓和。", 4, ["walk_home"]),
        },
        "walked_apart": {
            "rel": {"affection": -1},
            # v0.3：没有真正同行，就不能写 walk_home_done
            "narr": ["她站在路灯下没动，等你走出几步才转身。"],
            "mem": ("episode", "放学时没有一起走。", 3, ["walk_home"]),
        },
        "declined": {
            "rel": {"affection": -1},
            "narr": ["她点点头，没再多说。"],
            "mem": ("episode", "她拒绝了同行。", 2, ["walk_home"]),
        },
    },
    "shared_memory": {
        "shared_warmth": {
            "rel": {"trust": 2, "affection": 3},
            "narr": ["她说着说着，自己先笑了。"],
            "mem": ("episode", "两人一起翻起以前的事，气氛变暖。", 4, ["shared_memory"]),
        },
        "different_understanding": {
            "rel": {"trust": 1},
            "narr": ["同一件事，她记住的和你记住的不太一样。"],
            "mem": ("episode", "同一段记忆，两人的理解不同。", 3, ["shared_memory"]),
        },
        "memory_avoided": {
            "rel": {},
            "narr": ["她把话题轻轻带过去了。"],
            "mem": ("episode", "共同的记忆没有被接住。", 2, ["shared_memory"]),
        },
    },
    "unfinished_conversation": {
        "repaired": {
            "rel": {"trust": 4, "affection": 2},
            "facts": ["misunderstanding_resolved"],
            "narr": ["这一次她没有把话咽回去。"],
            "mem": ("promise", "两人把没说完的话说开了一些。", 5, ["unfinished"]),
        },
        "partially_understood": {
            "rel": {"trust": 2},
            "narr": ["她听完，点了点头，又停在那里。"],
            "mem": ("episode", "感受说出来了，但还没完全和解。", 4, ["unfinished"]),
        },
        "worsened": {
            "rel": {"respect_for_autonomy": -3, "trust": -2},
            "narr": ["她把脸别开，不想再继续这个话题。"],
            "mem": ("conflict", "又一次把话谈僵了。", 4, ["unfinished"]),
        },
        "avoided": {
            "rel": {},
            "narr": ["两个人都没有再往下说。"],
            "mem": ("episode", "没说完的话还是没说完。", 2, ["unfinished"]),
        },
    },
}


def resolve(
    state: dict[str, Any],
    storylet: Storylet,
    analysis: Analysis,
    outcome: str | None = None,
) -> Resolution | None:
    """finale 由结局引擎处理，这里返回 None 表示跳过。

    v0.3：事件结果由 `storylet_progress.evaluate()` 依据累积证据判定后传入；
    未传入时才退回旧的确定性默认值（保持 Mock/测试兼容）。
    """
    if storylet.kind == "finale":
        return None

    table = OUTCOMES.get(storylet.id)
    if not table:
        return Resolution(outcome=storylet.possible_outcomes[0] if storylet.possible_outcomes else "resolved")

    chosen = outcome if outcome in table else default_outcome(storylet, analysis)
    if chosen not in table:
        chosen = next(iter(table))

    spec = table[chosen]
    changes = gs.apply_relationship_delta(state, spec.get("rel", {}), f"{storylet.id}:{chosen}")
    changes += gs.apply_fact_changes(state, spec.get("facts", []), f"{storylet.id}:{chosen}")

    mem = spec.get("mem")
    memory = None
    if mem:
        kind, content, importance, tags = mem
        memory = (kind, content, importance, tags)

    return Resolution(
        outcome=chosen,
        changes=changes,
        narration=list(spec.get("narr", [])),
        memory=memory,
    )
