# demo1 最小后端

文件分工：main.py 编排流程和 HTTP；agent.py 定义 AI 能力；llm.py 连接模型；
state.py 定义存档状态；rules.py 定义程序规则；prompts.py 定义人物与任务。

## 启动

在 backend 目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 main.py
```

先在 .env 填写 DEEPSEEK_API_KEY。http://127.0.0.1:8000/docs 可测试。
旧 rpg 后端也用8000端口，先停止旧服务。不要同时启动两份。

## 接口

- GET /health：不调用模型。
- POST /start：无请求体，生成9月开场，返回 state 和 text。
- POST /step：发送上一次返回的完整 state 和 action。

```json
{"state": "这里替换为完整状态对象", "action": "dialogue", "text": "玩家的话"}
```

上例 state 是位置说明，实际必须为 JSON 对象，不是字符串。

| phase | 可用 action | 附加字段 |
| --- | --- | --- |
| dialogue | dialogue / end_dialogue | dialogue 时提供 text |
| plan | plan | text：计划；追问时再次提交补充 |
| relationship | relationship | accept：true 或 false |
| review | next | 无 |
| ended | 无 | 重新调用 /start 开新局 |

每次成功后整体替换 state，显示 text；不要把状态再次叠加。
失败保留旧状态重试，不消耗轮次、不提交数值。重复请求可能再次调用模型，
本版没有请求去重缓存；客户端应在请求时禁用发送，不并发提交。

/step 在 plan 成功结算后返回 review，不立即开启下月。点击继续发 next。
6月 review 的 next 生成终局，不创建第十一个场景。
服务没有状态数据库；Ren’Py 的 game_state 保存完整状态。

## 试玩假设与范围

- 每月汇总一次心动变化：-10 / 0 / +10。普通对话不立即奖励。
- 学习收益：0 / 4 / 8 / 12。6月只模拟考前7天：0 / 2 / 4。
- 合理投入可从学力10达到90，具体难度仍需真实试玩调整。
- 首次心动>=90时询问是否接受关系；拒绝后本版不自动重复询问。
- 人物信息通过提示词和新增记忆维持；没有复杂的事实冲突检测或承诺归档系统。
- 素材池、轮次、数值档位和阶段由程序检查；行动是否有效主要由AI判断。
- 采用 JSON 输出，仅检查核心规则，尚未加入完整的结构校验和错误恢复。
- 纯文本，无图片、音效；game/agent.rpy 连接后端，game/script.rpy 提供完整月度界面。

## 当前剧情与节点控制

小帅暗恋高冷同桌小美；母亲病重且温柔，希望他考上东京大学并独立生活。
班主任知道母亲情况，严厉督促学习，反对因恋爱分心。旧青梅家庭背景停用。
每个场景生成 purpose，AI 围绕目的简洁推进；完成或玩家不愿参与时，
返回 control: "break"，程序立即进入计划阶段。control: "continue" 才继续。
五轮为硬上限，玩家也可手动结束。主线不是强制任务，尊重玩家另选方向。

启动后端后，在 Ren’Py 启动 demo1（新设定请重新开局，勿加载旧剧情存档）。

## 同月多场景

一个月可包含多个场景，由AI按剧情需要选择，并非每月必须切换。
对话返回 control：continue 继续本场、switch_scene 结束本场并生成同月下一场、
break 结束整月对话并询问行动。切换需提供 transition_reason。
同月场景共用五轮上限，切换不清空对话和轮数；第五轮直接进入行动计划。
切换只显示地点标题与新场景对白，不再出现背景介绍；场景历史保存所有片段。
重启后端生效；推荐重新开局，旧进行中场景也可沿用但包含此前剧情记忆。
本次未加载或接入任何skill。
