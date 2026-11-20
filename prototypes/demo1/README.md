# demo1 月度校园剧情原型

一个独立的 Ren’Py 校园剧情实验。从 9 月到次年 6 月，玩家和角色自由聊天，再决定怎样分配学习、相处和家庭时间。每月结算心动与学力，并展示变化理由。

## 试玩

1. 在本目录的 `backend` 中创建 Python 虚拟环境并安装 `requirements.txt`。
2. 复制 `backend/.env.example` 为 `backend/.env`，填入自己的 DeepSeek API Key。
3. 在 `backend` 中执行 `python main.py`。后端监听本机 8000 端口。
4. 用 Ren’Py 启动本目录。客户端脚本使用 Ren’Py 8.5.3 检查。

完整接口和状态说明见 [后端 README](backend/README.md)。

## 可以一起试的方向

- 在 AfterTheBell 的规则与事件调度上加入「聊完这段之后，接下来打算怎么做」的阶段。demo1 已有自由填写计划和结算理由，可以先借用这段体验。
- 给 demo1 的月度流程加入 AfterTheBell 的事件前置条件和证据判定。在月内保留自由对话，让重要剧情结果可追溯到玩家的具体行为。
- 保持两个原型可分别运行，选一个场景验证上述组合，再决定是否统一存档与接口。
