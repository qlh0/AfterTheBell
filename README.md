# 那天放学后 / After the Bell

一个以**自由输入对话**为主要交互的校园恋爱视觉小说 Demo。
AI 负责自然对白，**可验证的规则**负责世界事实、事件触发与结局判定。

- 当前状态：**M1 已完成**——真实 LLM（DeepSeek / OpenAI 兼容）驱动许栀的对白，规则仍然掌控事实与结局。
- 平台：Ren'Py 8.6 桌面版；通信为普通 HTTP/JSON（无 SSE）。

![游戏界面（M1，DeepSeek 实时对白）](docs/ui_chat.jpg)

---

## 1. 30 秒上手

1. 复制 `.env.example` 为 `.env`，填入你的 `LLM_API_KEY`（DeepSeek 官方默认已配好）。
   `ATB_LLM_MODE=llm` 用真模型；`mock` 则离线跑模板对白。
2. 双击 **`run_dev.bat`**：起后端（独立窗口）→ 等 `/health` 就绪 → 打开游戏。

手动启动：

```powershell
# 终端 A：后端
cd D:\AfterTheBell\backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8756

# 终端 B：游戏
D:\renpy-8.6.0-sdk\renpy.exe D:\AfterTheBell
```

第一次从零搭环境：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

游戏里：在右侧输入框打字 → `发送`（或 Enter）；`推进时间` 相当于"结束这一幕/放学"；`结束本局` 回标题。
Esc 打开存档菜单。

---

## 2. 现在是什么状态

| 层 | 内容 |
|---|---|
| 客户端 | Ren'Py 8.6，中文 UI（内置思源黑体），聊天式自由输入，思考中提示，后端离线兜底，三种结局演出，读档快照对齐 |
| 角色 Agent | **M1：真实 LLM**（DeepSeek `deepseek-chat`，OpenAI 兼容接口），JSON 输出 + 校验 + 修复重试 + 兜底；`mock` 模式可离线 |
| 协议 | `POST /game/start`、`GET /game/{id}/state`、`POST /game/{id}/interact`、`POST /game/{id}/advance`、`GET /game/{id}/events`、`POST /game/{id}/restore/{version}` |
| 规则 | 前置条件 DSL、6 个 Storylet + 校门口 finale、4 个叙事目标、`eligible → prepared → committed` 结局状态机 |
| 存储 | SQLite：权威状态、逐版本快照、`request_id` 幂等、回合流水、事件日志、记忆、LLM 指标 |
| 测试 | **47 项 pytest**：三路线结局、幂等、版本冲突、无泄露、数值上限、LLM 解析/校验/兜底/指标 |

**设计红线（M1 依然成立）**

- AI 只提议，**规则**提交状态；非法动作直接丢弃。
- 普通对话**只调用一次**角色 Agent，不串行调导演。
- **玩家意图以规则解析为准**：模型提议的动作必须能在玩家这句话里找到依据，否则不算数（它不能替你表白）。
- **事件结果由规则判定**：模型的 `storylet_outcome` 只记录进事件日志用于调试，不直接改状态——避免模型把"玩家已经解释清楚"随手判成"只说开一半"，让结局不可达。
- 客户端只拿白名单 `scene_id/sprite_id` 和玩家可见文本；数值、事实名、角色秘密不下发。
- 关掉 Ren'Py 回滚；读档时用服务端快照把状态回退到存档点。

---

## 3. M1 角色 Agent 怎么工作

一次 `/interact` 里的模型调用：

```
状态/记忆/最近对话/当前事件
   → 组装 prompt（人设定性描述 + 她已知/未知 + 已发生事实 + 记忆 + 最近 8 轮 + 当前事件 + 可选动作）
   → DeepSeek /chat/completions（response_format=json_object，temperature 0.85，max_tokens 400）
   → 解析 JSON → 校验：
        · dialogue 非空、≤180 字、不含泄露词（好感度/数值/storylet/AI…）
        · emotion 必须在枚举内
        · actions 必须在白名单，且能在玩家这句话里找到依据
        · storylet_outcome 必须在事件的 possible_outcomes 内
   → 失败（超时 / 坏 JSON / 违规）最多重试一次 → 仍失败则模板兜底
   → 规则提交状态 → 记录 llm_calls 指标 → 返回完整 JSON
```

- Prompt 里**只给定性描述**（信任"较高"、亲近感"一般"），不给数字，模型就无从把数值当台词说出来。
- 她"不知道的事"和"绝不能主动说的秘密"写在 system prompt 里，作为防线；真正的兜底仍是后端的泄露词过滤。
- 每次调用的 `model / latency_ms / input_tokens / output_tokens` 会写进 `llm_calls` 表，`GET /game/{id}/events` 里能拿到汇总。
- 想临时断网玩：把 `.env` 里 `ATB_LLM_MODE=mock`。

---

## 4. 目录结构

```text
AfterTheBell/
├─ game/                      Ren'Py 客户端
│  ├─ script.rpy              主流程：开局 → 对话循环 → 结局
│  ├─ chat_screen.rpy         聊天面板 / 等待提示 / 离线提示 / 结局卡
│  ├─ ai_client.rpy           唯一的 HTTP 出口 + 存档对齐
│  ├─ options.rpy gui.rpy     标题、中文字体、菜单背景、关闭回滚
│  ├─ images/                 游戏用美术（1280×720 背景 / 高 700 透明立绘）
│  └─ fonts/                  思源黑体
├─ art_source/                美术原图（高分辨率，可追溯）
├─ backend/app/
│  ├─ main.py                 FastAPI 入口 + CORS + 错误映射
│  ├─ engine.py               一回合的完整编排
│  ├─ schemas.py              对外 HTTP 契约（Pydantic）
│  ├─ game_state.py           状态结构 / 数值上限 / 情绪→立绘映射
│  ├─ db.py                   SQLite 持久化 + 乐观并发 + 幂等 + 指标
│  ├─ content.py              内容加载与启动期校验
│  ├─ rules/                  前置条件、回合判定、动作效果、事件结果、结局
│  ├─ narrative/              Storylet 库、导演、调度
│  ├─ agents/                 角色 Agent（mock / llm / prompt 组装）
│  └─ memory/                 重要记忆写入与检索
├─ content/                   可编辑的叙事内容（JSON / prompt）
├─ tests/                     pytest（47 项）
├─ tools/
│  ├─ play.py                 终端模拟一局（不开 Ren'Py 也能验状态机）
│  ├─ prepare_art.py          原图 → 游戏规格（背景/立绘/菜单图）
│  └─ make_placeholder_art.py 无美术时的占位图生成
├─ docs/                      M0 / M1 验收记录
├─ run_dev.bat                一键启动（后端 + 游戏）
└─ .env.example               复制成 .env 后填 LLM Key
```

---

## 5. 一回合发生了什么

```
玩家输入
  → POST /interact（带 request_id + expected_state_version）
  → 读状态/记忆 → 激活已排期事件
  → 解析输入（话题/意图/是否有效互动）——规则
  → 角色 Agent（1 次 LLM；mock 模式下 0 次）
  → 动作白名单提交（数值有每回合上限）——规则
  → 事件收尾（结果由规则判定）——规则
  → 回合计数 → 场景推进 → 目标/结局资格
  → 必要时规划下一事件（当前仍是确定性打分；不调用 LLM）
  → 乐观并发写入 SQLite（状态 + 快照 + 幂等响应同一事务）
  → 返回完整 JSON → Ren'Py 渲染
```

导演（M2 才会接 LLM）只负责"下一个演什么"，且必须从 `storylets.eligible(state)` 里选；
普通闲聊不触发规划，避免每轮多一次模型调用。

---

## 6. 内容与规则在哪改

| 想改什么 | 改哪里 |
|---|---|
| 许栀的人设、她知道/不知道什么 | `content/characters.json` |
| 对白的口吻规则、禁止项 | `content/prompts/character_system.txt` + `backend/app/agents/prompts.py` |
| 加/删事件、改触发条件 | `content/storylets.json`（DSL 见下） |
| 事件每个走向的效果 | `backend/app/rules/storylet_resolution.py` 的 `OUTCOMES` 表 |
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

## 7. 测试与自检

```powershell
# 规则 + 契约 + 三路线 + LLM 校验（测试会强制 mock，不烧 token）
.venv\Scripts\python.exe -m pytest -q

# Ren'Py 静态检查（不需要窗口）
D:\renpy-8.6.0-sdk\renpy.exe D:\AfterTheBell lint

# 终端模拟一局（会按 .env 决定用 LLM 还是 mock）
.venv\Scripts\python.exe tools\play.py --route communicate --verbose
.venv\Scripts\python.exe tools\play.py --route control
.venv\Scripts\python.exe tools\play.py --route avoid
```

### 客户端链路自检（可选）

后端起着的时候：

```powershell
$env:ATB_SELFCHECK = "1"
D:\renpy-8.6.0-sdk\renpy.exe D:\AfterTheBell
Get-Content game\selfcheck.txt
```

会真实跑一遍"启动 → 发一句话 → 推进时间 → 渲染聊天面板 → 渲染结局卡 → 退出"。

---

## 8. 已知限制

1. **没有流式输出**：一次请求返回完整 JSON；LLM 单轮约 1.5–2.5 秒，界面只有"正在回复"提示。
2. **导演仍是确定性打分**（M2 才接 LLM）；`content/prompts/director_system.txt` 已预留。
3. **模型的事件结果提议只记录、不提交**：规则判定优先。等 M2 补齐导演与更细的证据校验后再开放。
4. **模型动作提议受严格证据约束**：漏掉玩家某些隐晦表达时，规则的关键词解析也可能漏，此时状态推进偏保守（宁可少给，不乱给）。
5. **存档**：关掉回滚；存档点与后端快照对齐，不支持跨分支回滚。
6. **中文输入法**：走 Ren'Py 的 IME 输入，未在 Web 版验证。
7. **成本**：每轮 prompt ≈1.3–1.5k tokens、输出 ≈40–70 tokens；测试不烧 token（强制 mock）。

---

## 9. 路线图

- **M2 导演**：把确定性打分换成"LLM 在合法候选里选"，`scheduled_storylet` + 版本复核（骨架已就绪）；让模型的事件结果提议在证据充分时参与判定。
- **M3 收束**：结局铺垫节奏、指标面板、消融对照（纯 LLM / +Storylet / +Director）、真人时长测试。

---

## 10. 依赖与许可

- Ren'Py 8.6（`D:\renpy-8.6.0-sdk`），字体 SourceHanSansLite（SIL OFL）。
- 后端：FastAPI / Pydantic / uvicorn / httpx / pytest / Pillow。
- 美术：`art_source/` 为原图，`game/images/` 为游戏规格图；占位图脚本保留在 `tools/make_placeholder_art.py`。
