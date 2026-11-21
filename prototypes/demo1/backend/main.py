"""HTTP入口与月度运行流程。启动：python3 main.py。"""
from copy import deepcopy
import logging
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import agent
import rules
from state import new_game, remember

app = FastAPI()
logger = logging.getLogger("uvicorn.error")


def context(state):
    return {
        "state": state,
        "month": rules.MONTHS[state["month_index"]],
        "period": rules.period(state),
        "locations": rules.LOCATIONS,
        "characters": rules.CHARACTERS,
        "remaining_turns": rules.MAX_TURNS - state["turns"],
        "allowed_love_changes": rules.LOVE_CHANGES,
        "allowed_study_gains": rules.study_gains(state),
    }


@app.exception_handler(ValueError)
async def invalid_generation(request, error):
    logger.error("AI格式校验失败: %s", error)
    return JSONResponse(status_code=502, content={
        "detail": "AI返回格式不正确，当前进度未提交，请重试。" + str(error)})


def checked_generation(generate, data, validate):
    # 最多纠正一次；校验通过前不写入状态。
    for attempt in range(2):
        result = None
        try:
            result = generate(data)
            validate(result)
            return result
        except ValueError as error:
            shape = {key: ("list[{}]".format(len(value)) if isinstance(value, list)
                           else type(value).__name__)
                     for key, value in result.items()} if isinstance(result, dict) else type(result).__name__
            logger.warning("AI格式纠正 %s/2: %s; 返回结构=%s", attempt + 1, error, shape)
            if attempt:
                raise
            data = {**data, "format_correction": (
                "上次输出格式错误：" + str(error)
                + "。请重新返回完整任务JSON；对白必须使用lines数组，不能使用text代替。")}


def dialogue_text(result, characters):
    if not isinstance(result, dict):
        raise ValueError("模型输出必须为JSON对象")
    lines = result.get("lines")
    # 兼容单句被包装成对象；不从自由正文猜测说话者或丢弃多余台词。
    if isinstance(lines, dict) and "speaker" in lines:
        lines = [lines]
        result["lines"] = lines
    if lines is None:
        raise ValueError("缺少lines字段；须返回lines:[{speaker,emotion,text}]")
    if not isinstance(lines, list):
        raise ValueError("lines必须为数组，实际为" + type(lines).__name__)
    if not lines:
        # 明确收场时可以没有新台词，系统直接询问计划或切换场景。
        if result.get("control") in ("break", "switch_scene"):
            return ""
        raise ValueError("继续对话或开场的lines不能为空")
    # 三句是写作建议，不是游戏轮数；超出时保留完整合法对白。

    rendered = []
    for line in lines:
        if not isinstance(line, dict):
            raise ValueError("lines中的每项必须为对象")
        if line.get("speaker") not in characters:
            raise ValueError("说话人物不在当前场景中")
        if not isinstance(line.get("text"), str) or not line["text"].strip():
            raise ValueError("对白不能为空")
        emotion = line.get("emotion", "")
        if not isinstance(emotion, str) or len(emotion) > 12:
            raise ValueError("情绪须为简短文字")
        rendered.append("{}{}：{}".format(
            line["speaker"], "（" + emotion + "）" if emotion else "", line["text"]))
    return "\n".join(rendered)


def open_scene(state, transition_reason=None):
    scene_context = context(state)
    scene_context["is_transition"] = transition_reason is not None
    scene_context["transition_reason"] = transition_reason
    def validate_scene(scene):
        if not isinstance(scene, dict):
            raise ValueError("场景必须为JSON对象")
        if scene.get("location") not in rules.LOCATIONS:
            raise ValueError("场景不在素材池中")
        characters = scene.get("characters")
        if not isinstance(characters, list) or not characters or not all(
                name in rules.CHARACTERS for name in characters):
            raise ValueError("characters必须为素材池中非空人物列表")
        if not isinstance(scene.get("purpose"), str) or not scene["purpose"].strip():
            raise ValueError("场景缺少节点目的purpose")
        if not isinstance(scene.get("time"), str) or not scene["time"].strip():
            raise ValueError("场景缺少time")
        if not isinstance(scene.get("intro", ""), str):
            raise ValueError("intro必须为字符串")
        dialogue_text(scene, characters)

    scene = checked_generation(agent.create_scene, scene_context, validate_scene)
    opening = dialogue_text(scene, scene["characters"])
    intro = scene.get("intro", "") if state["month_index"] == 0 and transition_reason is None else ""
    state.setdefault("scene_history", []).append({
        "month": rules.MONTHS[state["month_index"]],
        "location": scene["location"], "characters": scene["characters"],
        "purpose": scene["purpose"],
    })
    state["scene"] = scene
    if transition_reason is None:
        state["dialogue"] = []
        state["turns"] = 0
    state["phase"] = "dialogue"
    remember(state, scene.get("memory", {}))
    state["dialogue"].append({"role": "assistant", "content": "【" + scene["location"] + "】\n" + opening})
    return (intro + "\n\n" if intro else "") + "【" + scene["location"] + "】\n" + opening


def plan_question(state):
    return ("接下来这段时间，你打算做什么？"
            + "\n时间范围：" + rules.period(state)
            + "\n已记录承诺：" + "；".join(state["memory"]["promises"]))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/start")
def start():
    state = new_game()
    text = open_scene(state)
    return {"state": state, "text": text}


@app.post("/step")
def step(payload: dict):
    # 只操作副本。全部成功才返回，客户端用返回状态整体替换旧状态。
    state = deepcopy(payload["state"])
    action = payload["action"]
    text = ""

    if state["ended"]:
        raise HTTPException(400, "本局已经结束")

    if action == "dialogue" and state["phase"] == "dialogue":
        player_input = payload["text"]
        def validate_reply(result):
            if not isinstance(result, dict) or result.get("control") not in (
                    "continue", "switch_scene", "break"):
                raise ValueError("control必须为continue、switch_scene或break")
            if result["control"] == "switch_scene":
                reason = result.get("transition_reason")
                if not isinstance(reason, str) or not reason.strip():
                    raise ValueError("切场景须说明transition_reason")
            dialogue_text(result, state["scene"]["characters"])

        result = checked_generation(
            lambda data: agent.reply(data, player_input), context(state), validate_reply)
        reply_text = dialogue_text(result, state["scene"]["characters"])
        state["dialogue"] += [
            {"role": "user", "content": player_input},
            {"role": "assistant", "content": reply_text},
        ]
        state["turns"] += 1
        remember(state, result.get("memory", {}))
        text = reply_text
        if result["control"] == "break" or state["turns"] >= rules.MAX_TURNS:
            state["phase"] = "plan"
            text += "\n\n" + plan_question(state)
        elif result["control"] == "switch_scene":
            text += "\n\n" + open_scene(state, result["transition_reason"])

    elif action == "end_dialogue" and state["phase"] == "dialogue":
        state["phase"] = "plan"
        text = plan_question(state)

    elif action == "plan" and state["phase"] == "plan":
        # 澄清时保留原计划，再合并玩家回答，不开启NPC聊天。
        plan = state["plan"]
        plan = plan + "\n补充：" + payload["text"] if plan else payload["text"]
        result = agent.simulate_plan(context(state), plan)
        state["plan"] = plan
        if result["needs_clarification"]:
            text = result["question"]
        else:
            approved = rules.apply_settlement(state, result)
            state["simulation"] = result
            remember(state, result.get("memory", {}))
            state["summaries"].append(result["summary"])
            state["settlements"].append({
                "month": rules.MONTHS[state["month_index"]],
                "plan": plan, **approved,
            })
            # 先批准数值，再让AI按最终结果描写，避免正文与结算相反。
            text = agent.describe_settlement(context(state))["text"]
            state["phase"] = "review"
            if state["love"] >= rules.LOVE_TARGET and not state["relationship_offered"]:
                state["phase"] = "relationship"
                text += "\n\n小美愿意与你确认关系。你是否接受？"

    elif action == "relationship" and state["phase"] == "relationship":
        state["dating"] = payload["accept"]
        state["relationship_offered"] = True
        remember(state, {"facts": ["两人确认恋爱关系" if state["dating"] else "小帅暂未接受恋爱关系"]})
        state["phase"] = "review"
        text = "你们确认了恋爱关系。" if state["dating"] else "你暂未接受恋爱关系。"

    elif action == "next" and state["phase"] == "review":
        if state["month_index"] == len(rules.MONTHS) - 1:
            state["ending"] = {
                "admitted": state["study"] >= rules.STUDY_TARGET,
                "dating": state["dating"],
            }
            ending = agent.write_ending(context(state))
            state["ending"].update({
                "text": ending["text"],
                "xiaomei_studies": ending["xiaomei_studies"],
                "xiaomei_future": ending["xiaomei_future"],
            })
            state["phase"] = "ended"
            state["ended"] = True
            text = ending["text"]
        else:
            state["month_index"] += 1
            state["plan"] = ""
            state["simulation"] = {}
            text = open_scene(state)

    else:
        raise HTTPException(400, "当前阶段不能执行这个操作")

    return {"state": state, "text": text}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
