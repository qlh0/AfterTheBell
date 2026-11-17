# 消融对照（自动生成）

同一批玩家脚本，在三种配置下各跑一遍。

| 模式 | 路线 | 结局 | 回合 | 有效互动 | 触发事件 | LLM 调用 | prompt tokens | 角色均值/P95 (ms) |
|---|---|---|---|---|---|---|---|---|
| 纯 LLM 聊天 | communicate | friends | 11 | 9 | — | 11 | 22292 | 1503.6 / 1687 |
| + 条件 Storylet | communicate | romance | 10 | 8 | late_explanation、direct_question、walk_home、class_choice、school_gate_finale | 10 | 20068 | 1495.0 / 1905 |
| + LLM 导演 | communicate | romance | 10 | 8 | late_explanation、old_note、walk_home、class_choice、school_gate_finale | 15 | 24493 | 1424.7 / 1609 |
