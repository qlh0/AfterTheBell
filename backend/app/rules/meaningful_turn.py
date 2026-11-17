"""把玩家自由文本解析成「话题 + 有证据的动作 + 被拒绝的动作」。

v0.3 修正：不再用「全文命中关键词」直接推动作，而是先切小句，再在小句里判断
- 是不是引用别人的话（引号 / 陈屿说 / 她说）；
- 是不是否定（不、没、别、不要…）；
- 是不是假设（如果、要是、就算…）；
- 是不是疑问（吗、呢、？…）；
- 主语是玩家自己，还是别人。

原则：
- 提到某个话题 ≠ 玩家做了那个动作（提到「喜欢」不等于表白）；
- 高影响动作（表白、控制、支持自主、解释误会、承诺）必须有本句的直接证据；
- 拿不准时宁可不提交事实，也不反向改写状态。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# 话题 → 关键词。命中即认为玩家「提到」了这件事（仅用于上下文与事件证据）。
TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "distance": (
        "冷淡", "疏远", "躲", "不理", "不回", "消息", "回复", "怎么了", "最近",
        "生气", "怪你", "不对劲", "不理我", "看不见", "不理人", "在躲",
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
    "friend": ("做朋友", "还是朋友", "当朋友", "朋友就好", "只是朋友"),
    "controlling": (
        "不许", "不准", "别去", "不要去", "不要报", "必须", "听我的", "我替你",
        "为了我", "你得", "一定要", "我说了算", "放弃", "不准报", "别报",
    ),
    "leave": ("走了", "回家", "先走", "拜拜", "再见", "我走了", "先回去了", "明天见"),
    "smalltalk": ("天气", "作业", "考试", "午饭", "食堂", "哈哈", "今天", "学校", "值日", "笔记"),
}

# 动作规则：keywords + 允许问句 / 是否高影响 / 是否需要第一人称 / 目标检查
ACTION_RULES: dict[str, dict[str, Any]] = {
    "control_autonomy": {
        "keywords": ("不许", "不准", "别去", "不要去", "不要报", "必须", "听我的",
                     "我替你", "为了我", "你得", "一定要", "我说了算", "放弃", "不准报", "别报"),
        "allow_question": False,
        "target_required": True,
    },
    "support_autonomy": {
        "keywords": ("你自己决定", "你自己想", "我支持", "你想去就去", "尊重你",
                     "你的选择", "不要为了我", "不用为了我", "按你自己的想法",
                     "你自己选", "我不反对"),
        "allow_question": False,
        "ignore_negation": True,  # 「不要为了我」本身含否定词，但意思是支持
    },
    "explain_own_words": {
        "keywords": ("不是那个意思", "我是说", "我当时", "我说的是", "你别误会", "不是说你"),
        "allow_question": False,
        "ignore_negation": True,
    },
    "express_romance": {
        "keywords": ("喜欢你", "告白", "表白", "在一起", "交往", "女朋友", "心动",
                     "想和你在一起", "想和你"),
        "allow_question": False,
        "first_person_required": True,
    },
    "choose_friends": {
        "keywords": ("做朋友", "还是朋友", "当朋友", "朋友就好", "只是朋友"),
        "allow_question": False,
    },
    "clarify_quote": {
        "keywords": ("那句话", "误会", "澄清", "解释", "听见", "听到", "说清楚"),
        "allow_question": True,  # 「是不是跟那句话有关？」也算把话头引过来
    },
    "ask_distance": {
        "keywords": TOPIC_KEYWORDS["distance"],
        "allow_question": True,
    },
    "ask_chenyu": {
        "keywords": ("陈屿",),
        "allow_question": True,
    },
    "apology": {
        "keywords": ("对不起", "抱歉", "是我不好", "我错了", "别生气"),
        "allow_question": False,
    },
    "care": {
        "keywords": ("担心", "还好吗", "累", "别难过", "陪你", "注意", "早点回", "多吃"),
        "allow_question": True,
    },
    "promise": {
        "keywords": ("我会", "答应你", "我保证", "不会忘", "我等你", "陪你"),
        "allow_question": False,
        "ignore_negation": True,
    },
    "leave": {
        "keywords": ("走了", "回家", "先走", "拜拜", "再见", "我走了", "先回去了", "明天见"),
        "allow_question": False,
    },
    "small_talk": {
        "keywords": TOPIC_KEYWORDS["smalltalk"],
        "allow_question": True,
    },
    "recall_memory": {
        "keywords": ("记得", "还记得", "以前", "那次", "回忆", "便签", "那时候", "上次"),
        "allow_question": True,
    },
    "discuss_class_future": {
        # 关键词只是入口，真正判定见 analyze()：必须同时谈「分班计划」和「以后」
        "keywords": (),
        "allow_question": True,
    },
}

# 只有这些低风险动作允许模型补充；高影响动作必须由规则确认
MODEL_ADDABLE = {"care", "ask_distance", "ask_chenyu", "small_talk"}

MEANINGFUL_TOPICS = {
    "distance", "misunderstanding", "class_change", "romance", "chenyu",
    "care", "apology", "friend", "controlling",
}

QUESTION_MARKERS = ("?", "？", "吗", "呢", "怎么", "为什么", "什么", "是不是", "要不要", "能不能", "难道")
HYPOTHETICAL_MARKERS = ("如果", "要是", "假如", "万一", "就算", "即使", "哪怕", "倘若", "假设", "若是")
NEGATION_MARKERS = ("不", "没", "没有", "别", "不要", "不想", "不会", "从没", "并不", "未曾")
# 这些词里含「不/没」但不是否定动作，必须先剔除再判断
NEGATION_FALSE_FRIENDS = (
    "是不是", "不错", "不少", "差不多", "不管", "不论", "不仅", "不但",
    "不得不", "不光", "不好意思", "忍不住", "不得不", "不得不",
)
OTHER_SUBJECT_PREFIX = ("陈屿", "他", "她", "许栀", "人家", "别人", "你们")

_QUOTE_RE = re.compile(r"[「『“\"]([^」』”\"]*)[」』”\"]")
_CLAUSE_RE = re.compile(r"[，。！？；、,\n]+")
_WS_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    return _WS_RE.sub(" ", text.strip())


def _strip_quotes(text: str) -> str:
    """去掉引号里的内容：引用别人的话不产生玩家的动作。"""
    return _QUOTE_RE.sub(" ", text)


@dataclass
class Analysis:
    text: str
    normalized: str
    topics: set[str] = field(default_factory=set)
    actions: list[str] = field(default_factory=list)
    rejected_actions: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    is_question: bool = False
    hypothetical: bool = False
    quoted: bool = False
    controlling: bool = False
    is_meaningful: bool = False
    meaningful_reason: str = ""
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "topics": sorted(self.topics),
            "actions": self.actions,
            "rejected_actions": self.rejected_actions,
            "candidates": self.candidates,
            "is_question": self.is_question,
            "hypothetical": self.hypothetical,
            "quoted": self.quoted,
            "controlling": self.controlling,
            "is_meaningful": self.is_meaningful,
            "meaningful_reason": self.meaningful_reason,
        }


def _hits(text: str, words: tuple[str, ...]) -> bool:
    return any(w in text for w in words)


def _is_question(clause: str) -> bool:
    return _hits(clause, QUESTION_MARKERS)


def _is_hypothetical(clause: str) -> bool:
    return _hits(clause, HYPOTHETICAL_MARKERS)


def _is_negated(clause: str, keyword: str) -> bool:
    """关键词前面 6 个字内出现否定词，或小句以否定词开头。"""
    idx = clause.find(keyword)
    if idx < 0:
        return False
    window = clause[max(0, idx - 6): idx]
    for phrase in NEGATION_FALSE_FRIENDS:
        window = window.replace(phrase, " ")
    if _hits(window, NEGATION_MARKERS):
        return True
    return clause.lstrip().startswith(("不", "没", "别"))


def _other_subject(clause: str) -> bool:
    stripped = clause.strip()
    if stripped.startswith(OTHER_SUBJECT_PREFIX):
        return True
    # 「陈屿说……」「她说……」这类转述
    return bool(re.match(r"^(陈屿|他|她|许栀)(说|讲|问|告诉|觉得|认为)", stripped))


def _has_first_person(clause: str) -> bool:
    return _hits(clause, ("我", "咱", "我们"))


def _romance_targets_other(clause: str, keyword: str) -> bool:
    """「我喜欢陈屿」不算向许栀表白。"""
    idx = clause.find(keyword)
    if idx < 0:
        return False
    tail = clause[idx + len(keyword): idx + len(keyword) + 4]
    return tail.startswith(("陈屿", "他", "她", "别人"))


def _match_action(clause: str, action: str, spec: dict[str, Any]) -> str | None:
    """返回 accepted / rejected / candidate / None。"""
    keyword = next((w for w in spec["keywords"] if w in clause), None)
    if keyword is None:
        return None
    if _other_subject(clause):
        return "rejected"
    if _is_hypothetical(clause):
        return "candidate" if not spec.get("high_impact", True) else "rejected"
    if _is_question(clause) and not spec.get("allow_question", False):
        return "rejected"
    # 关键词本身自带否定（别去 / 不许 / 不要报）时，不要再按否定句处理
    keyword_has_negation = _hits(keyword, NEGATION_MARKERS)
    if (
        not spec.get("ignore_negation", False)
        and not keyword_has_negation
        and _is_negated(clause, keyword)
    ):
        return "rejected"
    if spec.get("first_person_required") and not _has_first_person(clause):
        return "rejected"
    if action == "express_romance" and _romance_targets_other(clause, keyword):
        return "rejected"
    if spec.get("target_required"):
        stripped = clause.strip()
        if not (
            _hits(clause, ("你", "她", "许栀", "我替你", "我说了算"))
            or stripped.startswith(keyword)
        ):
            return "candidate"
    return "accepted"


def analyze(text: str) -> Analysis:
    norm = normalize(text)
    unquoted = _strip_quotes(norm)
    quoted = unquoted != norm

    topics = {topic for topic, words in TOPIC_KEYWORDS.items() if _hits(norm, words)}
    clauses = [c.strip() for c in _CLAUSE_RE.split(unquoted) if c.strip()]
    if not clauses:
        clauses = [unquoted.strip()] if unquoted.strip() else []

    accepted: list[str] = []
    rejected: list[str] = []
    candidates: list[str] = []

    for clause in clauses:
        for action, spec in ACTION_RULES.items():
            verdict = _match_action(clause, action, spec)
            if verdict == "accepted" and action not in accepted:
                accepted.append(action)
            elif verdict == "rejected" and action not in rejected:
                rejected.append(action)
            elif verdict == "candidate" and action not in candidates:
                candidates.append(action)

    # 特别处理：否定「喜欢」= 拒绝恋爱；说「做朋友」= 选择朋友
    if "express_romance" in rejected and "friend" not in topics:
        for clause in clauses:
            if "喜欢" in clause and _has_first_person(clause) and not _is_question(clause):
                if "reject_romance" not in accepted:
                    accepted.append("reject_romance")
                break

    # 特别处理：同一句里既谈分班计划、又谈以后的相处 → 才算认真谈过分班
    future_words = ("以后", "未来", "分班后", "见不到", "一起走", "还能", "下学期", "还能见")
    plan_words = ("报", "考", "决定", "打算", "计划", "想读", "申请", "填")
    if (
        "class_change" in topics
        and any(w in norm for w in future_words)
        and (
            "support_autonomy" in accepted
            or "control_autonomy" in accepted
            or any(w in norm for w in plan_words)
        )
    ):
        accepted.append("discuss_class_future")

    # 高影响动作不允许出现在 candidates 里
    candidates = [a for a in candidates if a in MODEL_ADDABLE]
    accepted = list(dict.fromkeys(accepted))
    rejected = [a for a in dict.fromkeys(rejected) if a not in accepted]

    is_question = any(_is_question(c) for c in clauses) or _is_question(norm)
    hypothetical = any(_is_hypothetical(c) for c in clauses)
    controlling = "control_autonomy" in accepted

    meaningful = False
    reason = ""
    meaningful_actions = [a for a in accepted if a not in ("small_talk", "leave")]
    if controlling:
        meaningful, reason = True, "玩家在替她做决定"
    elif meaningful_actions:
        meaningful, reason = True, "玩家做出了动作：" + "/".join(meaningful_actions[:3])
    elif topics & MEANINGFUL_TOPICS:
        meaningful, reason = True, "触及关键话题：" + "/".join(sorted(topics & MEANINGFUL_TOPICS))
    elif "leave" in topics:
        meaningful, reason = True, "玩家表达了离场意图"
    elif is_question and len(norm) >= 5:
        meaningful, reason = True, "玩家提出了问题"
    elif len(norm) >= 14:
        meaningful, reason = True, "玩家主动说了较长的一段话"
    else:
        meaningful, reason = False, "闲聊/短回应"

    notes: list[str] = []
    if quoted:
        notes.append("contains_quoted_speech")
    if rejected:
        notes.append("rejected:" + ",".join(rejected))

    return Analysis(
        text=text,
        normalized=norm,
        topics=topics,
        actions=accepted,
        rejected_actions=rejected,
        candidates=candidates,
        is_question=is_question,
        hypothetical=hypothetical,
        quoted=quoted,
        controlling=controlling,
        is_meaningful=meaningful,
        meaningful_reason=reason,
        notes=notes,
    )


def resolve_actions(analysis: Analysis, proposed: list[str] | None) -> tuple[list[str], list[str]]:
    """规则动作 + 模型补充（只允许低风险动作）。返回 (最终动作, 说明)。"""
    final = list(analysis.actions)
    notes: list[str] = []
    for action in proposed or []:
        if action in final:
            continue
        if action in MODEL_ADDABLE and action not in analysis.rejected_actions:
            final.append(action)
            notes.append(f"model_added:{action}")
        else:
            notes.append(f"model_rejected:{action}")
    return final, notes


def primary_topic(analysis: Analysis) -> str:
    """给 mock 对白选模板时用的「主要话题」优先级。"""
    priority = [
        "controlling", "friend", "romance", "misunderstanding", "class_change",
        "distance", "chenyu", "apology", "care", "leave", "smalltalk",
    ]
    for topic in priority:
        if topic in analysis.topics:
            return topic
    return "smalltalk"
