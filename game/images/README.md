# 美术与素材

## 现状

基础场景（教室/校门口）与立绘为正式素材；第二天场景、走廊、图书馆、小卖部暂时是占位图，正式图到位后同名覆盖即可。流程是：

```
art_source/            # 原图（高分辨率，脚本只读）
  bg_classroom.png     1672×941
  bg_school_gate.png   1672×941
  xuzhi_normal.png     1037×1516（透明底）
  xuzhi_guarded.png    1037×1516（透明底）
  xuzhi_smile.png      1037×1516（透明底）
        │
        │  tools/prepare_art.py
        ▼
game/images/           # 游戏实际使用
  bg_classroom.png     1280×720（cover + 居中裁切）
  bg_school_gate.png   1280×720
  bg_corridor.png      1280×720（占位）
  bg_library.png       1280×720（占位）
  bg_shop.png          1280×720（占位）
  bg_classroom_day2.png    1280×720（占位）
  bg_school_gate_day2.png  1280×720（占位）
  xuzhi_*.png          479×700（等比缩放，透明底，底部对齐）
game/gui/
  main_menu_bg.png     1280×720
  game_menu_bg.png     1280×720
```

## 替换流程

1. 把新图放进 `art_source/`，文件名保持 `bg_classroom` / `bg_school_gate` / `xuzhi_normal` / `xuzhi_guarded` / `xuzhi_smile`（PNG）。
2. 跑 `.venv\Scripts\python.exe tools\prepare_art.py`。
3. 重新打开游戏即可。

立绘要求：人物底部贴齐图片底边，头顶留 2–5% 空白；画面显示时按 `yalign 1.0`
贴在屏幕底部（见 `game/script.rpy` 的 `sprite_pos`），宽高比由脚本等比处理。

新场景背景替换：
- 直接覆盖 `game/images/bg_corridor.png` / `bg_library.png` / `bg_shop.png` /
  `bg_classroom_day2.png` / `bg_school_gate_day2.png`；
- 如尺寸不是 1280×720，按 cover 裁切即可，`game/script.rpy` 已注册 image；
- 重新生成占位图：`.venv\Scripts\python.exe tools\make_scene_placeholders.py`。

## 想回到占位图

```powershell
.venv\Scripts\python.exe tools\make_placeholder_art.py
.venv\Scripts\python.exe tools\make_scene_placeholders.py
```

> 字体：`game/fonts/SourceHanSansLite.ttf`（思源黑体，SIL OFL），Ren'Py 内所有中文都由它渲染，
> 不依赖系统字体，后续 Web 版也不会掉字。
