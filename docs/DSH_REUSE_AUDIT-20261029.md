# 自研件复用审计（2026-10-29）

用户指出：仓库里 `dsh/` 开头的那些是上一轮自己写的，没有优先复用社区成熟项目。这份审计逐件对照，
每件都要回答一个问题：**别人有没有现成的、更好的实现？**

判断依据：本地社区快照 176 个插件（`.tools/dsh-vendor/review-find-plugin/data/registry-snapshot.json`）
+ 对候选件的 README 实际核对，不凭印象。

## 结论总表

| 自研件 | 功能 | 社区替代 | 决定 |
| --- | --- | --- | --- |
| `control/schedule.mjs` + 30 秒 tick | 每日定时触发 | **`dsh-routines`**（cron YAML、时区、overlap、超时、漏跑只补一次、审计记录） | **替换** |
| `service/fatfish_memory_mcp.py` 的 `bili_*` | B 站读取（16 个工具里的 6 个） | **`bili-cli`**（自带 Agent Skill，已装） | **删除重复** |
| `service/fatfish_memory_mcp.py` 的 memory | 记忆召回/候选/审核 | `dsh-memento`（审批门+可审计）、`dsh-mneme`、`dsh-memory-vault`、`dsh-memory` | **待评估迁移**（数据量大，需按群隔离验证） |
| `service/fatfish_memory_mcp.py` 的 `local_chat/local_check` | 峰谷本地模型 | 无对应；且峰谷切换方案本身未定 | **候选删除** |
| `service/fatfish_memory_mcp.py` 的 `steam_*` | Steam 价格 | 社区无 | 保留（薄封装既有 `fatfish_core/steam.py`） |
| `service/fatfish_memory_mcp.py` 的 `meme_*` | 自建 164 张图库 | `dsh-stickers`/`dsh-emoji` 是通用贴纸互动，不是按标签检索的自建图库 | 保留 |
| `service/fatfish_memory_mcp.py` 的 `tts_*` | 硅基流动克隆音色 | `dsh-voice` 是 edge-tts + ASR，换掉等于换声线 | 保留 |
| `policy.mjs` | 身份/静默/工作窗口/冷却/去重 | 社区无 QQ 策略件（`dsh-im-bridge` 是微信） | 保留 |
| `runtime-adapter.mjs` | 桥与策略的胶水 | 上游桥无此概念 | 保留 |
| `preset-apple-le.yml` | 人格 preset | 用的是官方 `dsh-persona`，preset 只是配置 | 保留 |
| `control/client.js` | 中文设置卡片 | DSH 原生 Settings 只投影 volatile 字段，第三方页面需自注册 | 保留（P6 已验收过渲染） |
| `control/ops.mjs` | 推荐筛选 | 无对应（业务规则） | 保留 |
| `skills/fatfish-bili` | B 站红线 | `bili-cli` 自带 skill 已装；本件改为纯约束层 | 保留（精简后） |
| `prepared-onebot` 补丁 | 桥的适配 | 桥本身即上游项目，补丁是必要的薄适配 | 保留 |
| 媒体发送 | 发语音/发图 | **桥上游自带 `qq_send_voice`/`qq_send_image`** | **删掉自研服务，恢复上游注册** |

## 替换一：调度 → dsh-routines

`dsh-routines` 与我的 `schedule.mjs` 功能重叠，且更完整：

| 能力 | 我的实现 | dsh-routines |
| --- | --- | --- |
| cron 表达式 | ❌ 只支持固定 HH:MM | ✅ 5 段 cron + `@daily`/`every 4h` |
| 时区 | 隐式本机 | ✅ 显式 IANA zone |
| 重叠保护 | ❌ | ✅ skip/queue/cancel-previous |
| 超时 | ❌ | ✅ timeoutMin |
| 漏跑策略 | 我自己定"超过 60 分钟不补" | ✅ 醒后最多补一次，绝不重放 |
| 运行审计 | 只写 `lastRun` | ✅ 每次一个 run record + 可读 digest |
| 审批策略 | ❌ | ✅ 无人值守强制 never，被拒项进记录 |

它的 routine 是 **YAML + prompt**，也就是"到点让一个 agent 去做这件事"，正好对上运营任务
（看首页推荐、写推荐理由、发私信）。**我的 tick 应该删掉。**

## 替换二：B 站工具 → bili-cli

MCP 里的 `bili_search`/`bili_video`/`bili_transcript`/`bili_comments`/`bili_check` 是在
封装 `bili-cli`。而 `bili-cli` 已经自带 Agent Skill（`bili skills show` 可导出，
`~/.claude/skills/bili-cli` 已装），命令知识不再需要我转述。

保留的只有红线约束（`fatfish-bili` skill），因为 bili-cli 的 skill 会教模型抽帧与转写，那是本项目禁止的。

## 替换三：媒体发送 → 桥上游工具

上游 `prepared-onebot/lib/tools.js` 里本来就有 `qq_send_voice` / `qq_send_image`，带限额、
审计、尺寸限制、NapCat 转码。是我们的 `prepare_dsh_onebot.py` 把 `registerTools` 整块删掉的。

正确做法：恢复注册，但只放行 `qq_send_voice`、`qq_send_image` 两个（`register(tool)` 处加白名单）。
我自己加的 `fatfishMedia` 服务应删除。

## 执行顺序（按收益/风险）

1. **删自研媒体服务 + 恢复上游两个工具**（净减代码，且能力更强）
2. **装 dsh-routines 替换自研调度**（需安装验证，之后 schedule.mjs 与 tick 删除）
3. **删 MCP 的 bili_* 与 local_* 工具**（能力由 bili-cli 覆盖；local 未定方案）
4. **评估记忆替换**（数据迁移风险最高，最后做，需先验证按群隔离与候选审核）

## 一条给自己的规矩

以后新增能力前先查三处：本地快照 176 个社区件 → `bili`/`dsh` 之类工具的 `--help` 与自带 skill →
现有仓库里是否已有。**查完再写，不要先写再补理由。**
