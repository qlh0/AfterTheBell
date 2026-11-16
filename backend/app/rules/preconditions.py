"""前置条件 DSL。

只支持声明式的白名单算子，绝不 eval 任意代码；内容文件写错会在加载时报错，
而不是在玩家游玩时静默放行/拒绝。

支持的算子（谓词是一个 dict，单键）：
    {"all": [p, ...]} / {"any": [p, ...]} / {"not": p}
    {"eq": [path, value]} / {"ne": [...]}
    {"gte": [path, n]} / {"lte": [...]} / {"gt": [...]} / {"lt": [...]}
    {"in": [path, [v, ...]]}
    {"flag": [path, bool]}                 # 布尔断言，值必须真的是 True/False
    {"truthy": path} / {"falsy": path}
    {"scene_in": ["classroom", ...]}
    {"turns_gte": n}                       # 有效互动回合数
    {"ending_phase_in": ["none", ...]}
    {"active_storylet_none": true}
    {"scheduled_storylet_none": true}
"""

from __future__ import annotations

from typing import Any

from .. import game_state as gs

OPERATORS = {
    "all", "any", "not",
    "eq", "ne", "gte", "lte", "gt", "lt",
    "in", "flag", "truthy", "falsy",
    "scene_in", "turns_gte", "ending_phase_in",
    "active_storylet_none", "scheduled_storylet_none",
}


class PredicateError(ValueError):
    pass


def validate(pred: Any, where: str = "") -> None:
    """内容加载时调用：把内容错误尽早暴露成启动失败。"""
    if not isinstance(pred, dict) or len(pred) != 1:
        raise PredicateError(f"{where}: 谓词必须是单键 dict，收到 {pred!r}")
    (op, arg), = pred.items()
    if op not in OPERATORS:
        raise PredicateError(f"{where}: 未知算子 {op!r}")
    if op in ("all", "any"):
        if not isinstance(arg, list):
            raise PredicateError(f"{where}: {op} 需要列表")
        for i, sub in enumerate(arg):
            validate(sub, f"{where}.{op}[{i}]")
    elif op == "not":
        validate(arg, f"{where}.not")
    elif op in ("eq", "ne", "gte", "lte", "gt", "lt"):
        if not isinstance(arg, list) or len(arg) != 2:
            raise PredicateError(f"{where}: {op} 需要 [path, value]")
        if not isinstance(arg[0], str):
            raise PredicateError(f"{where}: {op} 的 path 必须是字符串")
    elif op == "in":
        if not isinstance(arg, list) or len(arg) != 2 or not isinstance(arg[1], list):
            raise PredicateError(f"{where}: in 需要 [path, [values]]")
    elif op == "flag":
        if not isinstance(arg, list) or len(arg) != 2 or not isinstance(arg[1], bool):
            raise PredicateError(f"{where}: flag 需要 [path, bool]")
    elif op in ("truthy", "falsy"):
        if isinstance(arg, list):
            if len(arg) != 1 or not isinstance(arg[0], str):
                raise PredicateError(f"{where}: {op} 需要 path 或 [path]")
        elif not isinstance(arg, str):
            raise PredicateError(f"{where}: {op} 需要 path 字符串")
    elif op == "scene_in":
        if not isinstance(arg, list) or not all(isinstance(x, str) for x in arg):
            raise PredicateError(f"{where}: scene_in 需要字符串列表")
    elif op == "ending_phase_in":
        if not isinstance(arg, list):
            raise PredicateError(f"{where}: ending_phase_in 需要列表")
    elif op == "turns_gte":
        if not isinstance(arg, int):
            raise PredicateError(f"{where}: turns_gte 需要整数")
    elif op in ("active_storylet_none", "scheduled_storylet_none"):
        if arg is not True:
            raise PredicateError(f"{where}: {op} 仅支持 true")


def _loose_eq(a: Any, b: Any) -> bool:
    # 显式区分 bool 与 int，避免 True == 1 把事实判定搞混。
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b


def evaluate(pred: dict[str, Any], state: dict[str, Any]) -> bool:
    (op, arg), = pred.items()

    if op == "all":
        return all(evaluate(sub, state) for sub in arg)
    if op == "any":
        return any(evaluate(sub, state) for sub in arg)
    if op == "not":
        return not evaluate(arg, state)
    if op in ("eq", "ne"):
        path, expected = arg
        actual = gs.get_path(state, path)
        equal = _loose_eq(actual, expected)
        return equal if op == "eq" else not equal
    if op in ("gte", "lte", "gt", "lt"):
        path, expected = arg
        actual = gs.get_path(state, path)
        if actual is None or isinstance(actual, bool) or not isinstance(actual, (int, float)):
            return False
        return {
            "gte": actual >= expected,
            "lte": actual <= expected,
            "gt": actual > expected,
            "lt": actual < expected,
        }[op]
    if op == "in":
        path, allowed = arg
        return gs.get_path(state, path) in allowed
    if op == "flag":
        path, expected = arg
        return _loose_eq(gs.get_path(state, path), expected)
    if op == "truthy":
        path = arg[0] if isinstance(arg, list) else arg
        return bool(gs.get_path(state, path))
    if op == "falsy":
        path = arg[0] if isinstance(arg, list) else arg
        return not bool(gs.get_path(state, path))
    if op == "scene_in":
        return state.get("scene") in arg
    if op == "turns_gte":
        return int(state.get("meaningful_turns", 0)) >= arg
    if op == "ending_phase_in":
        return state.get("ending_phase") in arg
    if op == "active_storylet_none":
        return state.get("active_storylet") is None
    if op == "scheduled_storylet_none":
        return state.get("scheduled_storylet") is None

    raise PredicateError(f"未知算子 {op!r}")
