"""Agent能力；不推进月份、不计轮、不写入游戏状态。"""
from pathlib import Path
from llm import generate
import prompts


_SKILL_DIR = Path(__file__).resolve().parent.parent / "skills" / "galgame-scene-craft" / "references"
# 启动时读取，按阶段发送；修改技能文件后重启后端生效。
SCENE_CRAFT = (_SKILL_DIR / "scene.md").read_text(encoding="utf-8")
DIALOGUE_CRAFT = (_SKILL_DIR / "dialogue.md").read_text(encoding="utf-8")


def create_scene(context):
    return generate(prompts.WORLD + "\n" + SCENE_CRAFT + "\n" + prompts.SCENE, context)


def reply(context, player_input):
    return generate(prompts.WORLD + "\n" + DIALOGUE_CRAFT + "\n" + prompts.DIALOGUE,
                    {"context": context, "player_input": player_input})


def simulate_plan(context, plan):
    return generate(prompts.WORLD + prompts.PLAN,
                    {"context": context, "plan": plan})


def describe_settlement(context):
    return generate(prompts.WORLD + prompts.SETTLEMENT, context)


def write_ending(context):
    return generate(prompts.WORLD + prompts.ENDING, context)
