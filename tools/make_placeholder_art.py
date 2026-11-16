"""生成占位美术：两张背景 + 许栀三个表情。

正式素材到位后，直接把同名 PNG 覆盖到 game/images/ 即可，代码不用改。
规格：
    bg_classroom.png    1280x720
    bg_school_gate.png  1280x720
    xuzhi_normal.png    520x760 透明底（底部对齐画面下沿）
    xuzhi_guarded.png   520x760 透明底
    xuzhi_smile.png     520x760 透明底
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "game" / "images"
FONT_PATH = ROOT / "game" / "fonts" / "SourceHanSansLite.ttf"
S = 3  # 超采样倍数

W, H = 1280, 720
SW, SH = 520, 760

HAIR = (58, 40, 38, 255)
SKIN = (247, 224, 208, 255)
UNIFORM = (240, 242, 248, 255)
COLLAR = (58, 74, 116, 255)
RIBBON = (72, 92, 140, 255)
INK = (52, 44, 46, 255)


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size * S)


def vgrad(w: int, h: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (w, y)], fill=color)
    return img


def soft_light(img: Image.Image, box: tuple[int, int, int, int], color: tuple[int, int, int], alpha: int,
               blur: int = 40) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse(box, fill=(*color, alpha))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    img.alpha_composite(layer)


def stamp_text(img: Image.Image, text: str, xy: tuple[int, int], size: int = 15,
               alpha: int = 150, color: tuple[int, int, int] = (255, 255, 255)) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((xy[0] * S, xy[1] * S), text, font=font(size), fill=(*color, alpha))
    img.alpha_composite(layer)


def classroom() -> Image.Image:
    img = vgrad(W * S, H * S, (36, 40, 58), (86, 66, 74)).convert("RGBA")
    d = ImageDraw.Draw(img)

    win = (760 * S, 90 * S, 1190 * S, 430 * S)
    sky = vgrad(win[2] - win[0], win[3] - win[1], (120, 131, 168), (214, 158, 130))
    img.paste(sky, (win[0], win[1]))
    d.rectangle(win, outline=(210, 214, 226, 190), width=7 * S)
    for gx in range(win[0], win[2], 108 * S):
        d.line([(gx, win[1]), (gx, win[3])], fill=(210, 214, 226, 170), width=5 * S)
    d.line([(win[0], (win[1] + win[3]) // 2), (win[2], (win[1] + win[3]) // 2)],
           fill=(210, 214, 226, 170), width=5 * S)

    soft_light(img, (330 * S, 300 * S, 1210 * S, 760 * S), (255, 214, 176), 70, blur=70 * S // 4)

    desk = (30, 28, 40, 220)
    for row, y in enumerate((470, 590)):
        offset = 0 if row == 0 else 90
        for i in range(4):
            x = (40 + offset + i * 300) * S
            d.rounded_rectangle([x, y * S, x + 240 * S, (y + 26) * S], radius=8 * S, fill=desk)
            d.rectangle([x + 20 * S, (y + 26) * S, x + 34 * S, (y + 120) * S], fill=desk)
            d.rectangle([x + 206 * S, (y + 26) * S, x + 220 * S, (y + 120) * S], fill=desk)

    stamp_text(img, "教室 / 放学后", (36, 26), size=17)
    stamp_text(img, "占位素材 placeholder - 替换 game/images/bg_classroom.png", (36, 54), size=11, alpha=110)
    return img.convert("RGB")


def school_gate() -> Image.Image:
    img = vgrad(W * S, H * S, (24, 30, 48), (58, 48, 66)).convert("RGBA")
    d = ImageDraw.Draw(img)

    soft_light(img, (420 * S, 300 * S, 900 * S, 520 * S), (255, 186, 140), 60, blur=60 * S // 3)

    d.rectangle([0, 560 * S, W * S, H * S], fill=(33, 32, 42, 255))
    d.line([(0, 560 * S), (W * S, 560 * S)], fill=(120, 116, 132, 120), width=3 * S)

    gate = (17, 19, 28, 235)
    d.rectangle([400 * S, 220 * S, 880 * S, 246 * S], fill=gate)
    for x in range(410, 880, 47):
        d.rectangle([x * S, 246 * S, (x + 14) * S, 560 * S], fill=gate)
    d.rectangle([400 * S, 246 * S, 880 * S, 262 * S], fill=gate)

    for px in (390, 890):
        d.rectangle([(px - 26) * S, 200 * S, (px + 26) * S, 600 * S], fill=(26, 27, 36, 245))
    for lx in (390, 890):
        soft_light(img, ((lx - 90) * S, 90 * S, (lx + 90) * S, 240 * S), (255, 214, 160), 70)
        d.ellipse([(lx - 7) * S, 150 * S, (lx + 7) * S, 168 * S], fill=(255, 226, 180, 255))

    stamp_text(img, "校门口 / 傍晚", (36, 26), size=17)
    stamp_text(img, "占位素材 placeholder - 替换 game/images/bg_school_gate.png", (36, 54), size=11, alpha=110)
    return img.convert("RGB")


# ---------------- 立绘 ----------------

def _scale(seq):
    return [(x * S, y * S) for x, y in seq]


def _box(x0, y0, x1, y1):
    return [x0 * S, y0 * S, x1 * S, y1 * S]


def _face(d: ImageDraw.ImageDraw, mode: str) -> None:
    cx = 260
    eye_y = 246

    if mode == "guarded":
        # 视线偏开：眼睑压低、瞳孔靠边
        d.arc(_box(cx - 56, eye_y - 22, cx - 22, eye_y + 10), 195, 345, fill=INK, width=5 * S)
        d.arc(_box(cx + 22, eye_y - 22, cx + 56, eye_y + 10), 195, 345, fill=INK, width=5 * S)
        d.line([(cx - 44, eye_y - 10), (cx - 32, eye_y - 10)], fill=INK, width=6 * S)
        d.line([(cx + 32, eye_y - 10), (cx + 44, eye_y - 10)], fill=INK, width=6 * S)
    elif mode == "smile":
        d.arc(_box(cx - 56, eye_y - 26, cx - 22, eye_y + 8), 200, 340, fill=INK, width=5 * S)
        d.arc(_box(cx + 22, eye_y - 26, cx + 56, eye_y + 8), 200, 340, fill=INK, width=5 * S)
    else:
        d.ellipse(_box(cx - 50, eye_y - 20, cx - 28, eye_y + 6), fill=INK)
        d.ellipse(_box(cx + 28, eye_y - 20, cx + 50, eye_y + 6), fill=INK)

    brow = (96, 70, 66, 255)
    if mode == "guarded":
        d.line([(cx - 54, eye_y - 34), (cx - 26, eye_y - 28)], fill=brow, width=4 * S)
        d.line([(cx + 26, eye_y - 28), (cx + 54, eye_y - 34)], fill=brow, width=4 * S)
    else:
        d.arc(_box(cx - 58, eye_y - 46, cx - 22, eye_y - 24), 200, 340, fill=brow, width=4 * S)
        d.arc(_box(cx + 22, eye_y - 46, cx + 58, eye_y - 24), 200, 340, fill=brow, width=4 * S)

    mouth = (178, 104, 100, 255)
    if mode == "smile":
        d.arc(_box(cx - 24, 300, cx + 24, 326), 15, 165, fill=mouth, width=4 * S)
    elif mode == "guarded":
        d.line([(cx - 14, 314), (cx + 14, 314)], fill=mouth, width=4 * S)
    else:
        d.arc(_box(cx - 18, 302, cx + 18, 320), 25, 155, fill=mouth, width=4 * S)

    blush = (232, 160, 150, 72)
    d.ellipse(_box(cx - 88, 278, cx - 54, 300), fill=blush)
    d.ellipse(_box(cx + 54, 278, cx + 88, 300), fill=blush)


def sprite(mode: str) -> Image.Image:
    img = Image.new("RGBA", (SW * S, SH * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = 260

    # 后层长发
    d.ellipse(_box(cx - 102, 116, cx + 102, 372), fill=HAIR)
    d.polygon(_scale([(cx - 102, 240), (cx - 126, 520), (cx - 76, 520), (cx - 64, 320)]), fill=HAIR)
    d.polygon(_scale([(cx + 102, 240), (cx + 126, 520), (cx + 76, 520), (cx + 64, 320)]), fill=HAIR)

    # 脖子
    d.rectangle(_box(cx - 22, 330, cx + 22, 402), fill=SKIN)

    # 水手服
    d.polygon(_scale([
        (cx - 132, 404), (cx - 94, 372), (cx, 392), (cx + 94, 372), (cx + 132, 404),
        (cx + 152, SH), (cx - 152, SH),
    ]), fill=UNIFORM)
    d.polygon(_scale([(cx - 66, 384), (cx, 416), (cx + 66, 384),
                      (cx + 50, 364), (cx, 388), (cx - 50, 364)]), fill=COLLAR)
    d.polygon(_scale([(cx - 20, 402), (cx + 20, 402), (cx + 9, 476), (cx - 9, 476)]), fill=RIBBON)

    # 脸
    d.ellipse(_box(cx - 82, 138, cx + 82, 358), fill=SKIN)
    # 刘海
    d.polygon(_scale([
        (cx - 84, 226), (cx - 92, 158), (cx - 46, 128), (cx, 122), (cx + 46, 128),
        (cx + 92, 158), (cx + 84, 226), (cx + 58, 196), (cx + 22, 214),
        (cx - 16, 190), (cx - 52, 212),
    ]), fill=HAIR)
    # 鬓发
    d.polygon(_scale([(cx - 104, 168), (cx - 76, 210), (cx - 80, 372), (cx - 110, 360)]), fill=HAIR)
    d.polygon(_scale([(cx + 104, 168), (cx + 76, 210), (cx + 80, 372), (cx + 110, 360)]), fill=HAIR)

    _face(d, mode)

    if mode == "smile":
        d.ellipse(_box(cx + 66, 176, cx + 88, 198), fill=(226, 176, 120, 255))

    names = {"normal": "常规", "guarded": "戒备", "smile": "微笑"}
    stamp_text(img, f"许栀 / {names[mode]}（占位素材）", (12, SH - 26), size=11, alpha=120)

    return img.resize((SW, SH), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    classroom().resize((W, H), Image.LANCZOS).save(OUT / "bg_classroom.png")
    school_gate().resize((W, H), Image.LANCZOS).save(OUT / "bg_school_gate.png")
    for mode in ("normal", "guarded", "smile"):
        sprite(mode).save(OUT / f"xuzhi_{mode}.png")
    for p in sorted(OUT.glob("*.png")):
        print(f"{p.name:24s} {p.stat().st_size / 1024:8.1f} KB")


if __name__ == "__main__":
    main()
