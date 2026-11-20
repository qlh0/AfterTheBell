# 美术与素材

## 现状

基础场景、新场景与立绘都已替换为正式素材。第一天和第二天共用同一张教室/校门口背景，不再区分 `_day2` 文件。流程是：

```
art_source/            # 原图（高分辨率，脚本只读）
  bg_classroom.png
  bg_school_gate.png
  bg_corridor.png
  bg_library.png
  bg_shop.png
  xuzhi_normal.png
  xuzhi_guarded.png
  xuzhi_smile.png
  xuzhi_shy.png
  xuzhi_surprised.png
        │
        │  tools/prepare_art.py
        ▼
game/images/           # 游戏实际使用
  bg_classroom.png     1280×720（cover + 居中裁切）
  bg_school_gate.png   1280×720
  bg_corridor.png      1280×720
  bg_library.png       1280×720
  bg_shop.png          1280×720
  xuzhi_*.png          479×700（等比缩放，透明底，底部对齐）
game/gui/
  main_menu_bg.png     1280×720
  game_menu_bg.png     1280×720
```

## 替换流程

1. 把新图放进 `art_source/`，文件名保持 `bg_classroom` / `bg_school_gate` / `bg_corridor` / `bg_library` / `bg_shop` / `xuzhi_*`（PNG）。
2. 跑 `.venv\Scripts\python.exe tools\prepare_art.py`。
3. 重新打开游戏即可。

立绘要求：人物底部贴齐图片底边，头顶留 2–5% 空白；画面显示时按 `yalign 1.0`
贴在屏幕底部（见 `game/script.rpy` 的 `sprite_pos`），宽高比由脚本等比处理。

新场景背景（走廊/图书馆/小卖部）同样由 `prepare_art.py` 统一裁到 1280×720，并在第一天/第二天共用；
不再需要 `bg_*_day2.png`。

## 想回到占位图

```powershell
.venv\Scripts\python.exe tools\make_placeholder_art.py
.venv\Scripts\python.exe tools\make_scene_placeholders.py
```

> 字体：`game/fonts/SourceHanSansLite.ttf`（思源黑体，SIL OFL），Ren'Py 内所有中文都由它渲染，
> 不依赖系统字体，后续 Web 版也不会掉字。
