# 那天放学后 / After the Bell

一个以**自由输入对话**为主要交互的校园恋爱视觉小说 Demo。
AI 负责自然对白，**可验证的规则**负责世界事实、事件触发与结局判定。

- 当前状态：**M0 已完成**（不依赖 LLM 的可运行闭环），M1（真实 LLM 角色）待接入 Key。
- 平台：Ren'Py 8.6 桌面版；通信为普通 HTTP/JSON（无 SSE）。

---

## 1. 30 秒上手

```bat
run_dev.bat
```

它会：起后端（独立窗口）→ 等 `/health` 就绪 → 用 `D:\renpy-8.6.0-sdk\renpy.exe` 打开本项目。
关掉那个标题为 `AfterTheBell API` 的窗口即可停止后端。

手动启动：

```powershell
# 终端 A：后端
cd D:\AfterTheBell\backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8756

# 终端 B：游戏
D:\renpy-8.6.0-sdk\renpy.exe D:\AfterTheBell
```

> 第一次从零搭环境：
> ```powershell
> py -3.12 -m venv .venv
> .venv\Scripts\python.exe -m pip install -r backend\requirements.txt
> ```

游戏里：在右下输入框打字 → `发送`（或 Enter）；`推进时间` 相当于"结束这一幕/放学"；`结束本局` 回标题。
Esc 打开存档菜单。

---

## 2. 这一版（M0）做了什么

| 层 | 内容 |
|---|---|
| 客户端 | Ren'Py 8.6，中文 UI（内置思源黑体），聊天式自由输入，思考中提示，后端离线兜底，三种结局演出，读档快照对齐 |
| 协议 | `POST /game/start`、`GET /game/{id}/state`、`POST /game/{id}/interact`、`POST /game/{id}/advance`、`GET /game/{id}/events`、`POST /game/{id}/restore/{version}` |
| 规则 | 前置条件 DSL、6 个 Storylet + 校门口 finale、4 个叙事目标、`eligible → prepared → committed` 结局状态机 |
| 角色 | **Mock Agent**（模板对白，离线）；接口与 M1 的 LLM 版一致 |
| 存储 | SQLite：权威状态、逐版本快照、`request_id` 幂等、回合流水、事件日志、记忆、LLM 指标表 |
| 测试 | 37 项 pytest：三条玩家路线分别收束到 romance / friends / missed、幂等、版本冲突、无内部信息泄露、数值上限、事件不重复 |

**设计红线（已落实）**

- AI 只提议，**规则**提交状态；非法动作直接丢弃。
- 普通对话**只调用一次**角色 Agent，不串行调导演。
- 导演只在合法候选里选；候选先由 Python 过滤，提交前复核 `state_version`。
- 恋爱结局不靠好感度数值：需要"误会解开 + 谈过分班 + 玩家明确表达 + 她愿意 + 尊重过她的选择"。
- 客户端只拿白名单 `scene_id/sprite_id` 和玩家可见文本；数值、事实名、角色秘密不下发。
- 关掉 Ren'Py 回滚；读档时用服务端快照把状态回退到存档点。

---

## 3. 目录结构

```text
AfterTheBell/
├─ game/                      Ren'Py 客户端
│  ├─ script.rpy              主流程：开局 → 对话循环 → 结局
│  ├─ chat_screen.rpy         聊天面板 / 等待提示 / 离线提示 / 结局卡
│  ├─ ai_client.rpy           唯一的 HTTP 出口 + 存档对齐
│  ├─ options.rpy gui.rpy     标题、中文字体、菜单背景、关闭回滚
│  ├─ images/                 占位美术（替换说明见 images/README.md）
│  └─ fonts/                  思源黑体
├─ backend/
│  ├─ app/
│  │  ├─ main.py              FastAPI 入口 + CORS + 错误映射
│  │  ├─ engine.py            一回合的完整编排
│  │  ├─ schemas.py           对外 HTTP 契约（Pydantic）
│  │  ├─ game_state.py        状态结构 / 数值上限 / 情绪→立绘映射
│  │  ├─ db.py                SQLite 持久化 + 乐观并发 + 幂等
│  │  ├─ content.py           内容加载与启动期校验
│  │  ├─ rules/               前置条件、回合判定、动作效果、事件收尾、结局
│  │  ├─ narrative/           Storylet 库、导演、调度
│  │  ├─ agents/              角色 Agent（mock / llm 入口）
│  │  └─ memory/              重要记忆写入与检索
│  └─ requirements.txt
├─ content/                   可编辑的叙事内容（JSON / prompt）
│  ├─ characters.json         许栀、陈屿、玩家的人设与认知边界
│  ├─ narrative_goals.json    4 个抽象叙事目标 + 节奏预算
│  ├─ storylets.json          6 个条件事件 + finale
│  ├─ endings.json            三种结局的门槛与文本
│  └─ prompts/                M1/M2 的 prompt 草稿
├─ tests/                     pytest（三路线 + 契约 + 规则）
├─ tools/
│  ├─ play.py                 终端模拟一局（不开 Ren'Py 也能验状态机）
│  └─ make_placeholder_art.py 重新生成占位美术
├─ docs/M0_ACCEPTANCE.md      本里程碑验收记录与已知限制
├─ run_dev.bat                一键启动（后端 + 游戏）
└─ .env.example               复制成 .env 后填 LLM Key
```

---

## 4. 一回合发生了什么

```
玩家输入
  → POST /interact（带 request_id + expected_state_version）
  → 读状态/记忆 → 激活已排期事件
  → 解析输入（话题/意图/是否有效互动）
  → 角色 Agent（M0 模板 / M1 LLM，仅 1 次）
  → 动作白名单提交（数值有每回合上限）
  → 事件收尾（结果取决于玩家实际说了什么）
  → 回合计数 → 场景推进 → 目标/结局资格
  → 必要时规划下一事件（确定性打分；不调用 LLM）
  → 乐观并发写入 SQLite（状态 + 快照 + 幂等响应同一事务）
  → 返回完整 JSON → Ren'Py 渲染
```

导演（M0 为确定性打分）只负责"下一个演什么"，且必须从 `storylets.eligible(state)` 里选；
普通闲聊不触发规划，避免每轮多一次模型调用。

---

## 5. 内容与规则在哪改

| 想改什么 | 改哪里 |
|---|---|
| 许栀的人设、她知道/不知道什么 | `content/characters.json` |
| 加/删事件、改触发条件 | `content/storylets.json`（DSL 见下） |
| 结局门槛与结局文本 | `content/endings.json` |
| 节奏（有效互动预算） | `content/narrative_goals.json` 的 `pacing` |
| 动作效果数值 | `backend/app/rules/actions.py` |
| 哪些话算"有效互动" | `backend/app/rules/meaningful_turn.py` |

前置条件 DSL（内容写错会在**启动时**报错，不会静默放行）：

```json
{"all": [
  {"eq": ["scene", "classroom"]},
  {"gte": ["relationship.trust", 42]},
  {"in": ["ending_phase", ["none", "eligible"]]},
  {"flag": ["facts.misunderstanding_discussed", true]},
  {"falsy": ["active_storylet"]}
]}
```

支持：`all / any / not / eq / ne / gte / lte / gt / lt / in / flag / truthy / falsy /
scene_in / turns_gte / ending_phase_in / active_storylet_none / scheduled_storylet_none`。

---

## 6. 测试与自检

```powershell
# 规则 + 契约 + 三条路线
.venv\Scripts\python.exe -m pytest -q

# Ren'Py 静态检查（不需要窗口）
D:\renpy-8.6.0-sdk\renpy.exe D:\AfterTheBell lint

# 终端模拟一局（不开游戏）
.venv\Scripts\python.exe tools\play.py --route communicate --verbose
.venv\Scripts\python.exe tools\play.py --route control
.venv\Scripts\python.exe tools\play.py --route avoid
```

### 客户端链路自检（可选）

后端起着的时候：

```powershell
$env:ATB_SELFCHECK = "1"
D:\renpy-8.6.0-sdk\renpy.exe D:\AfterTheBell
Get-Content game\selfcheck.txt   # 会看到 boot/start/send/advance/screen_ok 全绿
```

它会在真实窗口里跑一遍"启动→发一句话→推进时间→渲染聊天面板→退出"，用于验证 Ren'Py 侧解析与界面没有回归。

---

## 7. 已知限制（M0 的边界）

1. **对白是模板**：同一话题只有 2–4 句轮换，事件期间玩家突然换话题时只能给一个短反应。这是 M1 换 LLM 要解决的第一件事。
2. **没有 LLM**：`ATB_LLM_MODE=mock`；`POST /interact` 的耗时基本 < 100ms。
3. **导演是确定性打分**，不是 M2 的 LLM 选择；`content/prompts/director_system.txt` 已预留。
4. **无流式**：一次请求返回完整 JSON；客户端用"许栀正在回复"提示等待，不做逐字流。
5. **存档**：关掉回滚；存档点与后端快照对齐（`/restore/{version}`）。跨分支游玩不受支持。
6. **中文输入法**：走 Ren'Py 的 IME 输入，未在 Web 版验证。
7. 美术是占位图（见 `game/images/README.md`）。

---

## 8. 路线图

- **M1 角色 Agent**：接 `ATB_LLM_MODE=llm`（DeepSeek 官方 / 任意 OpenAI 兼容端点），结构化 JSON 输出 + 修复重试 + 兜底台词；记忆召回进 prompt；输出泄露过滤。
- **M2 导演**：把确定性打分换成"LLM 在合法候选里选"，`scheduled_storylet` + 版本复核（骨架已就绪）。
- **M3 收束**：结局铺垫节奏、日志/指标面板、消融对照（纯 LLM / +Storylet / +Director）、真人时长测试。

---

## 9. 依赖与许可

- Ren'Py 8.6（`D:\renpy-8.6.0-sdk`），字体 SourceHanSansLite（SIL OFL）。
- 后端：FastAPI / Pydantic / uvicorn / httpx / pytest / Pillow。
- 占位美术由 `tools/make_placeholder_art.py` 生成，无第三方素材版权问题。
