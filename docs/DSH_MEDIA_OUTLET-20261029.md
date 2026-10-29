# P-B 媒体出口方案（待选型）

日期：2026-10-29。目标：最终回复 → 媒体决策 → TTS/选图 → OneBot 发出 → 真实回执。
这是迁移表里唯一「代码写了但没接线」的一环，卡在一个选型上，不是卡在能力上。

## 现状（已核实）

| 事实 | 依据 |
| --- | --- |
| 桥本身能发媒体 | `prepared-onebot/lib/tools.js` 注册了 `qq_send_image` / `qq_send_voice` / `qq_send_video` / `qq_send_file` / `qq_send_segments` |
| 主动写有独立闸门 | `actionRatePerMinute`(20) / `actionRatePerDay`(500) + `qq-actions.log` 审计 |
| 桥自己不决定发不发 | `Config` 里**没有任何** TTS/概率字段，只负责「让发就发」 |
| 决策逻辑已存在 | `fatfish_core/delivery.py`，经 MCP `delivery_prepare` / `delivery_finish` 暴露（P3.4，8 项回归） |
| 社交 preset **没有**这些工具 | P1 主动撤掉的：工具 schema 会让模型往编程/后台命令方向规划 |

所以缺口只有一个：**谁在回合结束后按概率去调用发送**。

## 三个候选

### A. 重新注册媒体工具，交给模型自己调

- 改动最小：把 `qq_send_voice` 等加回社交 preset，靠提示词表达「15% 概率发语音」
- 问题：概率不可控（模型不是随机数发生器）；工具面污染会把其他回合的规划带偏——这正是 P1 撤掉它们的理由
- 结论：**不推荐**，除非只想「能发就行」

### B. 桥暴露 host 服务，控制插件在回合结束按概率发送（推荐）

- 桥侧：在 `apply()` 里 `ctx.set('fatfishMedia', { sendVoice, sendImage })`，内部转调已有的 `bridge.sendSegments`
- 决策侧：控制插件监听回合结束，调 MCP `delivery_prepare` 拿决策，按结果调用该服务，再用 `delivery_finish` 记回执
- 优点：概率由代码决定（可复现、可测）；模型工具面完全不变；复用桥已有的限额与审计
- 代价：要改上游适配（`prepared-onebot` 是仓库自己的适配产物，`prepare_dsh_onebot.py` 已有补丁管线），并更新归档哈希

### C. 自建薄插件直连 OneBot HTTP 发送

- 会形成第二条连接，绕过桥的限额、审计、去重
- 与 AGENTS.md「避免多套语音路由/并行引擎」冲突
- 结论：**不推荐**

## 推荐 B 的最小实现范围

1. `prepared-onebot/lib/index.js`：`ctx.set('fatfishMedia', ...)`，只暴露 sendVoice/sendImage，不接受任意 segment
2. `dsh/control/index.mjs`：回合结束钩子 → `delivery_prepare` → 条件发送 → `delivery_finish`
3. 失败语义：合成或发送失败**保留原文**，不吞消息；语音成功则**只发语音**（沿用旧基线）
4. 临时文件：发送后回收，异常路径也要回收
5. 会话隔离：服务调用必须带 chatId，跨会话调用直接拒绝

## 验收标准（离线可测，不需要真实 QQ）

- 概率：固定种子下 15% 语音 / 35% 表情的抽样与 `fatfish_core/delivery.py` 一致
- 失败：mock 合成失败 → 原文照发，且 `delivery_finish(voice_sent=false)`
- 成功：mock 发送成功 → 只发语音，文字不重复发
- 越权：用别的 chatId 调用服务 → 拒绝并记审计
- 回执：`qq-actions.log` 有对应记录，`delivery_finish` 与之一致
- 默认值不变：`allowSynthesis=false`、语音 15%、表情 35%

## 需要拍板的两件事

1. 是否接受**改动上游适配**（B 的前提）。不改就得选 A，接受概率不可控
2. 语音合成默认仍关闭（`allowSynthesis=false`）；启用后是**按次收费**，要不要先只接「表情/图片」、语音留到你当场看着试
