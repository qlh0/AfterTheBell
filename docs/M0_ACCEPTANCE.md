# M0 验收记录（2026-11-16）

对应用户文档 `After_the_Bell_CodingAgent_开发说明_v0.2.md` §10 的 M0：
"不依赖 LLM，至少三条测试路线都能以合法事件与结局收束"。

## 1. 交付物

| 项 | 位置 |
|---|---|
| Ren'Py 工程（可双击运行） | `game/` + `run_dev.bat` |
| FastAPI 后端 | `backend/app/` |
| 内容（角色/事件/目标/结局） | `content/*.json` |
| 测试 | `tests/`（37 项） |
| 终端试玩 | `tools/play.py` |
| 占位美术 + 规格 | `game/images/` + `ready-to-replace` 说明 |

## 2. 自动化证据

### pytest（三条路线 + 契约 + 规则）

```text
$ .venv\Scripts\python.exe -m pytest -q
.....................................                                    [100%]
[exit=0]
```

覆盖：

- `test_routes.py`：三条玩家脚本分别收束到 `romance` / `friends` / `missed`，且比对的是**服务端内部状态**（trust、respect、facts），不是对白；
- `test_api.py`：`request_id` 重试幂等（不重复提交）、`state_version` 冲突返回 409、404、空文本 422、结束后再交互 409、`/advance` 换场景、快照 restore、响应不包含内部字段；
- `test_rules.py`：DSL 各算子、bool 与 int 不混用、数值 0–100 截断、单回合变化上限、未知动作被丢弃、`affection=100` 也不给恋爱结局、finale 只在校门口成立。

### Ren'Py lint

```text
$ renpy.exe <repo> lint
Ren'Py 8.6.0.26111403 lint report
Statistics: 0 menus, 5 images, 28 screens
lint_exit=0
```

### 客户端链路自检（真实窗口 + 真实 HTTP）

```powershell
$env:ATB_SELFCHECK = "1"; renpy.exe <repo>
```

`game/selfcheck.txt`：

```text
boot=True
start_err=None
game_id=demo_9de37084
send_err=None turn=1 version=1
advance_err=None scene=school_gate sprite=xuzhi_normal
chat_log=8
screen_ok res=('quit', None)
ending_screen_ok res=True
done
```

说明：Ren'Py 侧从探活、开局、发一句话、推进时间、渲染聊天面板到渲染结局卡，全链路无异常。

### 一键启动

`run_dev.bat` 实测：后端在 8756 就绪（`/health` 200），Ren'Py 主窗口标题为"那天放学后"并正常打开。

```text
=== health ===
OK api=0.3.0-m0
=== renpy window ===
Id     MainWindowTitle
11068  那天放学后
```

## 3. 三路线结果（终端复现）

| 路线 | 输入策略 | 结局 | 关键状态 |
|---|---|---|---|
| 主动沟通 | 关心 → 澄清那句话 → 支持她自己选 → 表达心意 | `romance`《下学期，也一起走吧》 | `misunderstanding_resolved=true`、`class_change_discussed=true`、`mutual_intent=romance`，约 8–10 回合收束 |
| 过度干预后补救 | "你不许去重点班""我替你决定" → 道歉、澄清、把选择权还给她 | `friends`《还是和以前一样》 | 干预时 `player_controlling=true`、尊重值当场下降；补救后 `mutual_intent=friendship`，没有替玩家表白 |
| 持续回避 | 只回"嗯/哦/哈哈" | `missed`《那天没说出口的话》 | 误会从未进入讨论，平静收场 |

复现命令：

```powershell
.venv\Scripts\python.exe tools\play.py --route communicate --verbose
.venv\Scripts\python.exe tools\play.py --route control
.venv\Scripts\python.exe tools\play.py --route avoid
```

## 4. 已验证的约束

- 普通对话只有一次角色 Agent 调用；Director 在 M0 是确定性打分，不产生额外 LLM 调用。
- 状态提交先于 HTTP 响应；状态、快照、幂等响应在同一 SQLite 事务里写入。
- `expected_state_version` 不符 → 409，客户端同步后提示"那句话没有送达"。
- 响应里没有 `relationship` / `facts` / `narrative_goals` / 角色秘密；`committed_changes` 只保留 `scene`、`ending_phase`。
- 立绘/场景只接受白名单 id（Pydantic `Presentation` 校验 + Ren'Py 侧固定映射）。
- `once` 事件不会重复；已用事件列表可在内部状态核对。
- 角色秘密（`characters.json.secrets_not_for_player_view`、`known_beliefs.truth`）不出现在任何响应中。

## 5. 已知限制（M0 → M1 的输入）

1. 对白是模板轮换，事件期间玩家突然换话题只能给一句短反应 → M1 换 LLM 解决。
2. 导演尚未接 LLM（骨架 `narrative/director.py` + `content/prompts/director_system.txt` 已就绪）。
3. 无流式；单轮完整等待，客户端只有"正在回复"提示。
4. 存档只保证与后端快照对齐；不支持跨分支回滚。
5. 中文输入法仅在 Windows 桌面版实测（自检未覆盖真人输入，需人工确认）。
6. 占位美术需替换（规格见 `game/images/README.md`）。

## 6. 下一步（M1）

1. 实现 `agents/llm_character.py`：OpenAI 兼容 `/chat/completions`、JSON 模式、超时重试、失败兜底模板。
2. Prompt 组装：人设 + 已知/未知事实 + 近期对话 + 关键记忆 + 当前事件 + 动作白名单。
3. 动作/结果校验：LLM 提议必须在白名单与 `possible_outcomes` 内，且能在玩家本轮文本找到依据。
4. 输出泄露扫描：禁止数值、系统提示、客观真相外泄。
5. 指标入库：延迟、token、失败率（`llm_calls` 表已就绪）。
