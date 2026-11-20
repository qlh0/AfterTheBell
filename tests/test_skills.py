"""写作规范文件是任务级 prompt 的一部分，不能缺失。"""

from __future__ import annotations

from pathlib import Path

from app.agents import prompts
from app.content import load_content

ROOT = Path(__file__).resolve().parents[1]
CRAFT = ROOT / "content" / "prompts" / "writing"


def test_writing_craft_files_exist_and_are_nonempty():
    for name in ("dialogue", "scene", "ending"):
        path = CRAFT / f"{name}.txt"
        assert path.exists(), f"缺少写作规范：{path}"
        assert path.read_text(encoding="utf-8").strip()


def test_scene_prompt_covers_all_scene_ids():
    assert prompts.SCENE_CN["classroom"] == "教室（放学后）"
    assert prompts.SCENE_CN["school_gate"] == "校门口（傍晚）"
    assert prompts.SCENE_CN["corridor"] == "走廊"
    assert prompts.SCENE_CN["library"] == "图书馆"
    assert prompts.SCENE_CN["shop"] == "小卖部"


def test_prompt_loads_dialogue_scene_and_ending_crafts():
    content = load_content()

    dialogue = prompts.system_prompt(content)
    assert "对白写作规范" in dialogue

    scene_storylet = content.storylets.get("old_note")
    assert scene_storylet is not None
    scene_prompt = prompts.system_prompt(content, scene_storylet)
    assert "场景写作规范" in scene_prompt

    finale = content.storylets.get("school_gate_finale")
    assert finale is not None
    ending_prompt = prompts.system_prompt(content, finale)
    assert "结局写作规范" in ending_prompt
