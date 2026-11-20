"""运行素材尺寸检查：防止再次出现立绘/背景超出 1280×720。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "game" / "images"


def test_runtime_images_fit_screen():
    for path in sorted(IMAGES.glob("bg_*.png")):
        assert Image.open(path).size == (1280, 720), f"{path.name} 未裁到 1280×720"
    for path in sorted(IMAGES.glob("xuzhi_*.png")):
        width, height = Image.open(path).size
        assert height <= 720, f"{path.name} 高度 {height} 超出画面"
        assert width <= 1280, f"{path.name} 宽度 {width} 超出画面"
