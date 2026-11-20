# 那天放学后

[![tests](https://github.com/qlh0/AfterTheBell/actions/workflows/tests.yml/badge.svg)](https://github.com/qlh0/AfterTheBell/actions/workflows/tests.yml)

AI 校园恋爱视觉小说演示：**Ren'Py 8.6 客户端 + FastAPI/SQLite 后端**。
你用自由输入和她聊天，AI 负责自然对白，**规则**负责世界事实、事件触发与结局判定。

> 不是选项式 Galgame：没有固定选项树，只有“她怎么接你这句话”和“哪些事真的发生了”。

---

## 1. 项目特点

- **自由输入**：直接打字聊天；界面给 2–4 句可参考的说法，点一下填进输入框，也可以自己改。
- **规则权威**：模型只提议动作和台词；关系值、事实、事件结果、结局都由服务端规则提交，模型不能替你表白或改写结局。
- **事件有明确阶段**：进行中 → 互动中 → 已解决 / 已放弃，必须有互动证据；一句无关的话不会自动完成事件。
- **两天时间线**：第一天教室 → 第一天校门口 → 第二天教室 → 第二天校门口；「推进时间」会按这个顺序切换，关键节点也会自动推进；玩家说「明天见」或到第 15 轮左右，她会主动收束到第二天，并黑屏显示「第二天 / 放学后」。
- **日常插曲**：放学后去图书馆、在走廊聊两句、一起去小卖部。可以点提示，也可以直接说「去图书馆 / 去小卖部」触发；进入插曲后会真正切换背景并停留至少两轮，小卖部结束后默认留在小卖部，只有玩家说「回校门口」才会回去。
- **三条线索**：她为什么疏远你、那句被误解的话、分班之后怎么相处；线索状态会进入导演决策。
- **三种结局**：恋爱 / 朋友 / 错过，由双方意愿、事实与关系值共同决定。
- **约 20 轮，22 轮必结束**：到硬上限前会先进入校门口收束，用一段有效对话把结局说完，不会直接黑屏。
- **读档 = 新时间线**：每次读档创建新分支，只继承读档点之前的对话/记忆/事件，不会“看到未来”。
- **对局记录**：结局时自动保存本局记录（结局、状态、事件链、完整对话），同时写入 SQLite、JSON、Markdown。
- **可测试**：159 项 pytest，覆盖语义反例、事件证据、分支隔离、结局门槛、两天场景、插曲事件、素材尺寸、记录等；测试不消耗 API Token。

## 2. 技术栈

| 层 | 技术 |
|---|---|
| 客户端 | Ren'Py 8.6（Python 脚本 + screen 语言） |
| 后端 | Python 3.12、FastAPI、Pydantic 2、uvicorn |
| 存储 | SQLite（状态、快照、回合流水、记忆、事件、指标、对局记录） |
| 模型 | DeepSeek `deepseek-chat`（OpenAI 兼容接口） |
| 测试 | pytest（强制 mock，不需要真实 Key） |

```text
Ren'Py 客户端  ──HTTP/JSON──▶  FastAPI 后端  ──▶  SQLite
      │                          │
      └── 只拿可展示文本 ────────┘  ├── 规则引擎（事实/关系/事件/结局）
                                   └── DeepSeek API（对白 + 导演）
```

服务端是唯一权威状态；客户端不保存数值、事实名或角色秘密。

---

## 3. 环境要求

| 依赖 | 版本 / 说明 | 必须 |
|---|---|---|
| **Ren'Py SDK** | **8.6.x**，提供 `renpy.exe` / `renpy.sh` | ✅ 运行客户端 |
| **Python** | **3.12+**（后端，不能复用 Ren'Py 自带 Python） | ✅ |
| **DeepSeek API Key** | 在 <https://platform.deepseek.com/> 创建 | ✅ 正式游玩 |
| 操作系统 | Windows 10/11、macOS（Linux 也可，用 `renpy.sh`） | — |
| Git | 拉取仓库 | 建议 |

> `mock` 模式只用于自动化测试/离线开发，**不是正式游玩方式**；没有 Key 时后端会拒绝启动。

---

## 4. 快速开始（Windows）

### 4.1 安装 Ren'Py 8.6 SDK

1. 打开 <https://www.renpy.org/latest.html>，下载 **Ren'Py 8.6** 的 SDK；
2. 解压到一个固定目录，例如 `C:\renpy-8.6.0-sdk`；
3. 可选：设置环境变量 `RENPY_HOME` 指向该目录（推荐，启动器会优先使用）：

```bat
setx RENPY_HOME "C:\renpy-8.6.0-sdk"
```

> 启动器也会自动搜索 `Downloads`、用户目录、`C:\`、`D:\` 下的 `renpy-*` 目录；找不到时再手动设置 `RENPY_HOME`。

### 4.2 安装 Python 3.12

从 <https://www.python.org/downloads/> 安装 Python 3.12，安装时勾选 **Add python.exe to PATH**。

### 4.3 拉取并初始化

```bat
git clone https://github.com/qlh0/AfterTheBell.git
cd AfterTheBell
setup.bat
```

`setup.bat` 会创建 `.venv` 并安装 `backend/requirements.txt`。

### 4.4 配置 API Key（必填）

```bat
copy .env.example .env
notepad .env
```

把 `LLM_API_KEY=` 后面填成你的 DeepSeek Key：

```ini
ATB_LLM_MODE=llm
LLM_API_KEY=sk-你的真实Key
```

> `.env` 已被 `.gitignore` 忽略，不会提交；不要把它发给别人。

### 4.5 启动

```bat
run_dev.bat
```

它会：
1. 检查 `.env` / Key；
2. 启动 FastAPI（`http://127.0.0.1:8756`）；
3. 等待 `/health` 就绪；
4. 打开 Ren'Py 客户端；
5. 游戏退出后关闭由它启动的后端。

---

## 5. 快速开始（macOS）

### 5.1 安装 Ren'Py 8.6 SDK

从 <https://www.renpy.org/latest.html> 下载 macOS 版 SDK，解压/安装到例如 `~/renpy-8.6.0-sdk`，然后：

```bash
export RENPY_HOME="$HOME/renpy-8.6.0-sdk"
```

建议写入 `~/.zshrc` 持久化。

### 5.2 安装 Python 3.12

```bash
brew install python@3.12
# 或者从 https://www.python.org/downloads/ 安装
```

### 5.3 拉取并初始化

```bash
git clone https://github.com/qlh0/AfterTheBell.git
cd AfterTheBell
chmod +x setup.command run_dev.command run_backend.command
./setup.command
```

### 5.4 配置 Key

```bash
cp .env.example .env
${EDITOR:-nano} .env    # 填 LLM_API_KEY
```

### 5.5 启动

```bash
./run_dev.command
```

或在 Finder 里双击 `run_dev.command`（首次可能需要在“系统设置 → 隐私与安全性”里允许）。

> 如果提示 “cannot be opened because the developer cannot be verified”，右键 → 打开；仍不行时执行 `xattr -dr com.apple.quarantine .`。

---

## 6. 手动启动（不用一键脚本）

### Windows

```bat
:: 终端 A：后端
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8756

:: 终端 B：客户端
"%RENPY_HOME%\renpy.exe" .
```

### macOS / Linux

```bash
# 终端 A：后端
.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8756

# 终端 B：客户端
"$RENPY_HOME/renpy.sh" .
```

游戏默认连接 `http://127.0.0.1:8756`；如果改端口，需要同时改 `ATB_PORT` 和客户端设置。

---

## 7. 配置项（`.env`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `ATB_LLM_MODE` | `llm` | `llm` 正式游玩；`mock` 仅测试 |
| `LLM_API_KEY` | 空 | **必填**，DeepSeek API Key |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI 兼容接口地址 |
| `LLM_MODEL` | `deepseek-chat` | 模型名 |
| `ATB_PORT` | `8756` | 后端端口 |
| `ATB_TURN_BUDGET` | `14` | 有效互动预算 |
| `ATB_DIRECTOR` | `1` | 是否让 LLM 在关键节点选事件 |
| `ATB_ALLOW_MOCK` | `0` | 仅测试：允许 `mock` 模式 |

没有 `LLM_API_KEY` 时：

- `run_dev` 会直接报错并提示怎么填；
- 直接启动后端会抛出 `RuntimeError: 未配置 LLM_API_KEY...`，不会静默降级成 mock。

---

## 8. 怎么玩

- 在底部输入框打字，`Enter` 发送；
- 上方 chip 是可参考的说法，点击填入输入框，可自行修改；**点过的说法不会重复出现**；
- 旁白页只显示旁白，点「继续」进入对话；对话页只显示她这一句 + 输入框；
- `推进时间` 按顺序切换：第一天教室 → 第一天校门口 → 第二天教室 → 第二天校门口；
- `结束本局` 回到标题；
- 右上角「聊天记录」展开完整对话；
- `Esc` 打开存档菜单；读档会在服务端创建新分支。

---

## 9. 项目结构

```text
AfterTheBell/
├─ game/                    Ren'Py 客户端
│  ├─ script.rpy            入口、主循环、存档
│  ├─ chat_screen.rpy       对话/旁白面板、聊天记录、结局卡
│  ├─ ai_client.rpy         HTTP 客户端、状态同步
│  └─ images/ gui/ fonts/   美术与字体
├─ backend/
│  ├─ app/
│  │  ├─ main.py            FastAPI 入口
│  │  ├─ engine.py          单回合编排
│  │  ├─ db.py              SQLite 访问与迁移
│  │  ├─ records.py         对局记录
│  │  ├─ agents/            角色 Agent、prompt、mock/LLM
│  │  ├─ narrative/         storylet、调度、导演
│  │  └─ rules/             语义、动作、事实、结局、线索
│  ├─ data/                 运行时数据库/记录（gitignored）
│  └─ requirements.txt
├─ content/                 storylets、goals、endings、角色设定
├─ tests/                   pytest
├─ tools/                   dev.py / setup_env.py / play.py / ablation.py
├─ docs/                    设计与验收文档、截图
├─ setup.bat / setup.command
└─ run_dev.bat / run_dev.command
```

---

## 10. 测试

```bat
:: Windows
.venv\Scripts\python.exe -m pytest -q

:: macOS / Linux
.venv/bin/python -m pytest -q
```

- **159 项**，全部在 mock 模式下运行，不需要 Key、不消耗 Token；
- 覆盖：语义反例（否定/引用/疑问/假设）、事件证据与放弃、读档分支隔离、结局门槛、NPC 主动意图、目标谓词、对局记录、解释识别、同行邀请宽限等；
- 真实模型手测：`tools/play.py --route communicate|control|avoid`（需要后端和 Key）。

### 客户端自检（可选）

```powershell
$env:ATB_SELFCHECK = "1"
# 启动后端后运行 Ren'Py
renpy.exe .
Get-Content game\selfcheck.txt
```

会跑一遍“启动 → 发一句话 → 推进时间 → 渲染面板/记录/结局卡 → 退出”。

---

## 11. 内容怎么改

| 文件 | 内容 |
|---|---|
| `content/storylets.json` | 事件、前置条件、可能的走向、背景旁白 |
| `content/narrative_goals.json` | 叙事目标与 `progress_if` / `done_if` 谓词 |
| `content/endings.json` | 三种结局的门槛与文本 |
| `content/characters.json` | 角色人设、说话方式、秘密 |
| `content/prompts/` | 角色 system prompt |

改完先跑 `pytest`，再用 `tools/play.py` 跑三条路线。

---

## 12. API 与对局记录

常用接口：

```text
POST /game/start
POST /game/{id}/interact
POST /game/{id}/advance
GET  /game/{id}/state
GET  /game/{id}/events
GET  /game/{id}/metrics
GET  /game/{id}/record
GET  /records
POST /game/{id}/restore/{version}
```

结局后记录会写到：

- SQLite `game_records` 表；
- `backend/data/records/<game>_<branch>.json`
- `backend/data/records/<game>_<branch>.md`（含完整对话，适合复盘）

---

## 13. 常见问题

**Q：启动时提示“未配置 LLM_API_KEY”**
复制 `.env.example` 为 `.env`，填入 DeepSeek Key；确认没有多余引号/空格。

**Q：提示“没有找到 Ren'Py SDK”**
安装 Ren'Py 8.6，设置 `RENPY_HOME` 指向 SDK 根目录（里面有 `renpy.exe` / `renpy.sh`）。

**Q：macOS 双击 `.command` 没反应**
先 `chmod +x setup.command run_dev.command`；再右键 → 打开。仍不行看“隐私与安全性”。

**Q：端口 8756 被占用**
在 `.env` 里改 `ATB_PORT`，并确认没有另一个后端在跑。

**Q：游戏显示“连不上后端”**
看启动器所在终端；常见是 Key 未填、依赖未装、端口冲突。

**Q：API 报 401/429**
Key 无效或额度不足；到 DeepSeek 控制台检查。API 失败时角色会走兜底台词，但体验不完整。

**Q：能不用 Key 玩吗？**
不能。`mock` 仅供测试；正式游玩必须配置 Key。

**Q：Windows 终端中文乱码？**
用 `run_dev.bat`（内部已 `chcp 65001`）；手动运行时先执行 `chcp 65001`。

---

## 14. 已知限制

- 目前是**两天、一个女主、12 个事件、3 个结局**的演示，完整时长约 20 轮（15–20 分钟）；
- 语义解析是规则 + 小句启发式，长复句/反讽可能漏判；
- 上下文窗口较短（最近若干条流水 + 记忆），长局靠 facts/记忆延续；
- 导演同步调用，关键回合多 1–2 秒；
- 没有流式输出、语音、移动端/Web；
- 测试以 mock 为主，真实 LLM 存在随机性，已用 `tools/play.py` 做手测。

## 15. 许可

仓库暂未附带 LICENSE 文件。如果你希望以 MIT / Apache-2.0 等方式开源，请补充 `LICENSE` 并在 GitHub 的 About 里选择对应许可。

## 16. 致谢

- [Ren'Py](https://www.renpy.org/)：视觉小说引擎
- [FastAPI](https://fastapi.tiangolo.com/) / [Pydantic](https://docs.pydantic.dev/)
- [DeepSeek](https://www.deepseek.com/)：对白与导演模型
- 字体：Source Han Sans（SIL OFL）
