"""程序规则；标注为试玩假设的值可在试玩后调整。"""
MONTHS = ["9月", "10月", "11月", "12月", "1月", "2月", "3月", "4月", "5月", "6月"]
MAX_TURNS = 5
LOVE_TARGET = 90
STUDY_TARGET = 90
LOCATIONS = ["教室", "回家路上", "便利店", "小帅家", "小美家"]
CHARACTERS = ["班主任", "同学A", "同学B", "同学C", "小帅妈妈", "小美"]

# 试玩假设：每月只汇总一次心动变化；学习按实际完成情况分四档。
LOVE_CHANGES = [-10, 0, 10]
STUDY_GAINS = [0, 4, 8, 12]
# 试玩假设：6月场景固定在高考前7天，只模拟这7天，学习最多+4。
JUNE_DAYS = 7
JUNE_STUDY_GAINS = [0, 2, 4]


def period(state):
    return f"高考前剩余{JUNE_DAYS}天" if state["month_index"] == 9 else "当月场景之后至月底"


def study_gains(state):
    return JUNE_STUDY_GAINS if state["month_index"] == 9 else STUDY_GAINS


def apply_settlement(state, simulation):
    love = simulation["love_delta"]
    study = simulation["study_delta"]
    # 最小的规则检查：不允许模型自行突破数值档位。
    if type(love) is not int or love not in LOVE_CHANGES:
        raise ValueError("心动变化不在允许档位内")
    if type(study) is not int or study not in study_gains(state):
        raise ValueError("学习收益不在本月允许档位内")
    before = {"love": state["love"], "study": state["study"]}
    state["love"] = max(0, min(100, state["love"] + love))
    state["study"] = max(0, min(100, state["study"] + study))
    return {
        "before": before,
        "after": {"love": state["love"], "study": state["study"]},
        "love_reason": simulation["love_reason"],
        "study_reason": simulation["study_reason"],
    }
