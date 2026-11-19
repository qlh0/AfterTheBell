"""为新场景生成占位背景（正式图到位后直接同名覆盖）。

生成：
    bg_corridor.png          走廊
    bg_library.png           图书馆
    bg_shop.png              小卖部
    bg_classroom_day2.png    第二天教室
    bg_school_gate_day2.png  第二天校门口
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "game" / "images"
FONT_PATH = ROOT / "game" / "fonts" / "SourceHanSansLite.ttf"
W, H = 1280, 720

SCENES = {
    "corridor": ("走廊", (34, 45, 62), (96, 112, 132), "放学后的走廊，窗外是操场"),
    "library": ("图书馆", (52, 43, 34), (128, 104, 76), "放学后的图书馆，靠窗的位置"),
    "shop": ("小卖部", (70, 47, 30), (160, 112, 62), "校门口的小卖部，暖黄的灯"),
    "classroom_day2": ("第二天 教室", (38, 40, 64), (92, 78, 102), "第二天放学后，教室里只剩下你们"),
    "school_gate_day2": ("第二天 校门口", (28, 34, 54), (104, 72, 78), "第二天傍晚，校门口的路灯"),
}


def gradient(top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / max(1, H - 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (W, y)], fill=color)
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    title_font = ImageFont.truetype(str(FONT_PATH), 54)
    sub_font = ImageFont.truetype(str(FONT_PATH), 22)
    hint_font = ImageFont.truetype(str(FONT_PATH), 16)

    for name, (title, top, bottom, subtitle) in SCENES.items():
        img = gradient(top, bottom)
        draw = ImageDraw.Draw(img)
        # 简单的地平线/光斑，让占位图不至于完全空白
        draw.rectangle([0, int(H * 0.72), W, H], fill=(20, 22, 30))
        draw.ellipse([int(W * 0.58), int(H * 0.16), int(W * 0.82), int(H * 0.52)],
                     fill=(255, 214, 160))
        draw.text((64, 58), title, font=title_font, fill=(255, 246, 232))
        draw.text((66, 126), subtitle, font=sub_font, fill=(230, 220, 206))
        draw.text((66, H - 52), "占位背景 / 之后替换为正式素材", font=hint_font,
                  fill=(190, 182, 174))
        path = OUT / f"bg_{name}.png"
        img.save(path)
        print(f"{path.name:28s} {path.stat().st_size / 1024:8.1f} KB")


if __name__ == "__main__":
    main()
