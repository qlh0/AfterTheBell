"""可交给 Ren'Py 存档的 JSON 状态；后端不额外保存会话。"""

def new_game():
    return {
        "month_index": 0,
        "phase": "scene",
        "turns": 0,
        "love": 50,
        "study": 10,
        "dating": False,
        "relationship_offered": False,
        "ended": False,
        "scene": {},
        "scene_history": [],
        "dialogue": [],
        "memory": {
            "facts": [],
            "known": [],
            "promises": [],
            "unresolved": [],
            "character_details": [],
        },
        "plan": "",
        "simulation": {},
        "settlements": [],
        "summaries": [],
        "ending": {},
    }


def remember(state, additions):
    # 追加首次确立的事实，不把已发生事实覆盖成另一个版本。
    for category in state["memory"]:
        for item in additions.get(category, []):
            if item not in state["memory"][category]:
                state["memory"][category].append(item)
