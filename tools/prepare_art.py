"""把美术原图整理成 Ren'Py 直接可用的规格。

原图存放在 `art_source/`（不覆盖、可追溯）；本脚本从原图生成：
    game/images/bg_classroom.png     1280x720（cover + 居中裁切）
    game/images/bg_school_gate.png   1280x720
    game/images/xuzhi_*.png          高 700，等比缩放，透明底
    game/gui/main_menu_bg.png        1280x720
    game/gui/game_menu_bg.png        1280x720

替换美术的流程：把新图放进 art_source/（同名），再跑一次本脚本。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "art_source"
IMAGES = ROOT / "game" / "images"
GUI = ROOT / "game" / "gui"

SCREEN = (1280, 720)
SPRITE_HEIGHT = 700

BACKGROUNDS = ("bg_classroom", "bg_school_gate")
SPRITES = ("xuzhi_normal", "xuzhi_guarded", "xuzhi_smile")


def ensure_sources() -> None:
    """第一次运行时，把当前 game/images 里的图当作原图存档。"""
    SRC.mkdir(parents=True, exist_ok=True)
    for name in BACKGROUNDS + SPRITES:
        dest = SRC / f"{name}.png"
        if not dest.exists():
            current = IMAGES / f"{name}.png"
            if current.exists():
                shutil.copy2(current, dest)
                print(f"备份原图: {current} -> {dest}")


def cover_resize(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    scale = max(target_w / img.width, target_h / img.height)
    new_size = (round(img.width * scale), round(img.height * scale))
    img = img.resize(new_size, Image.LANCZOS)
    left = (img.width - target_w) // 2
    top = (img.height - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def sprite_resize(img: Image.Image, height: int) -> Image.Image:
    scale = height / img.height
    width = round(img.width * scale)
    return img.resize((width, height), Image.LANCZOS)


def main() -> None:
    ensure_sources()
    IMAGES.mkdir(parents=True, exist_ok=True)

    for name in BACKGROUNDS:
        src = Image.open(SRC / f"{name}.png").convert("RGB")
        out = cover_resize(src, SCREEN)
        out.save(IMAGES / f"{name}.png")
        print(f"{name}.png -> {out.size[0]}x{out.size[1]}")

    for name in SPRITES:
        src = Image.open(SRC / f"{name}.png").convert("RGBA")
        out = sprite_resize(src, SPRITE_HEIGHT)
        out.save(IMAGES / f"{name}.png")
        print(f"{name}.png -> {out.size[0]}x{out.size[1]}")

    GUI.mkdir(parents=True, exist_ok=True)
    for name, target in (("bg_classroom", "main_menu_bg.png"), ("bg_school_gate", "game_menu_bg.png")):
        src = Image.open(SRC / f"{name}.png").convert("RGB")
        cover_resize(src, SCREEN).save(GUI / target)
        print(f"gui/{target}")


if __name__ == "__main__":
    main()
