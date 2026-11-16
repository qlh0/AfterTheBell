# 占位美术说明

现在这套是脚本生成的占位资源（`tools/make_placeholder_art.py`），
用于让工程立刻可跑。正式素材到位后，**直接同名覆盖**即可，代码不用改。

| 文件 | 尺寸 | 说明 |
|---|---|---|
| `bg_classroom.png` | 1280×720 | 教室，放学后傍晚光 |
| `bg_school_gate.png` | 1280×720 | 校门口，傍晚路灯 |
| `xuzhi_normal.png` | 520×760，透明底 | 许栀·常规 |
| `xuzhi_guarded.png` | 520×760，透明底 | 许栀·戒备/回避视线 |
| `xuzhi_smile.png` | 520×760，透明底 | 许栀·微笑 |

立绘要求：人物底部贴齐图片底边，头顶留少量空白；画面显示时按
`yalign 1.0` 贴在屏幕底部（见 `game/script.rpy` 的 `sprite_pos`）。

重新生成占位图：

```powershell
.venv\Scripts\python.exe tools\make_placeholder_art.py
```

> 字体：`game/fonts/SourceHanSansLite.ttf`（思源黑体，SIL OFL），Ren'Py 内所有中文都由它渲染，
> 不依赖系统字体，后续 Web 版也不会掉字。
