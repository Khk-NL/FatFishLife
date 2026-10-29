# FatFishLife → DSH 全功能迁移对照表

更新：2026-10-29。本表取代「AstrBot 继续承担生产」的旧假设：**用户已决定弃用 AstrBot，全部功能迁入官方 DSH**。
规则：每个能力先查能否复用 DSH 社区插件；社区没有的，用仓库已有 `fatfish_core` 经 MCP 暴露（复用既有代码，不另写引擎）；确实需要新写的只做薄适配。

生态盘点来源：`.tools/dsh-vendor/review-find-plugin/data/registry-snapshot.json`（176 个精选社区插件，离线快照，2026-10-28）。
GitHub 实时搜索 2026-10-29 已触发限流（HTTP 403，anonymous 10 次/分钟），后续以本地快照为准。

## 一、社区生态覆盖结论

DSH 社区插件生态明显小于 AstrBot，且**大多是面向「编码/工作台」的通用件**，与本项目「QQ 群聊人格机器人 + 运营」的形态不重合。
176 个精选件里，能直接复用的很少；多数能力的正确路径是「DSH 原生能力 + 自有 fatfish_core + 薄适配」。

| 能力域 | 社区可复用 | 结论 |
| --- | --- | --- |
| QQ/OneBot 通道 | 无（仅有微信 iLink 桥 `dsh-im-bridge`） | 用已适配的上游 `dsh-onebot-qq` 0.9.6（BSD-3），仓库内 `.tools/dsh-vendor/prepared-onebot` 已就绪 |
| 记忆 | 多（`dsh-memory-vault`/`dsh-memento`/`dsh-mneme`/`dsh-mnemon`） | **不复用**：本项目需要按群/会话隔离、候选审核、中文风格，`fatfish_core` 已实现且无 AstrBot 依赖 |
| 知识库/笔记 | `dsh-knowledge-base` 0.1.5、`dsh-obsidian` 0.2.6 | **已装并生效** |
| B 站 | `dsh-plugin-bilibili` 0.2.4 | **已装（适配版只开文本）**；`dsh-video-downloader` 按 AGENTS.md 红线**禁用**（不下载音视频） |
| TTS | `dsh-voice`(edge-tts)、`dsh-gptsovits-tts`、`dsh-mimotts`、`dsh-mmx-bridge` | **不复用**：现用硅基流动克隆音色 1.1 倍，换插件等于换声线；走 `fatfish_core/tts.py` + MCP |
| 联网搜索 | DSH 原生 `web_search`；可选 `modsearch`/`argo` | **用原生**，不装 `anysearch` |
| 定时/主动 | `dsh-routines`、`dsh-automation`、`dsh-loop` + 原生 schedule | **可复用**：主动消息改用社区 cron 级插件或原生 schedule |
| 表情包 | `dsh-stickers`、`dsh-emoji` | **不复用**：那是通用贴纸互动，本项目的 164 张自建图库需 `fatfish_core/gallery.py` |
| Steam | 无 | `fatfish_core/steam.py` + MCP；促销追踪待薄适配 |
| Pixiv / 音乐 / 电子书 / 漫画 | 基本无（`dsh-netease-island` 只是状态挂件不可点歌） | 薄适配或按需放弃，**排在最后** |
| 群风格学习 | `distill` 相近但场景不同 | 复用 `fatfish_core` 风格模块 |

## 二、逐项迁移表

状态列含义：`已就绪`＝DSH 侧实现且有证据；`待接`＝实现存在但未接入出口；`待适配`＝需写薄适配；`原生覆盖`＝不用迁；`保留`＝保持独立工具。

| # | 能力 | AstrBot 来源 | DSH 方案 | 类型 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 1 | QQ 收发通道 | 内置 aiocqhttp(napcat) | `prepared-onebot`（上游 0.9.6，BSD-3） | 复用社区 | 已就绪（P1.2/P1.3 隔离证据，未装生产） |
| 2 | 会话记忆 | fatfish_memory | `fatfish_core` MemoryStore 经 MCP | 复用自有 | 已就绪（MCP 工具在线） |
| 3 | 私人笔记 | fatfish_obsidian + obsidian_sync | `dsh-obsidian` 0.2.6 | 复用社区 | 已就绪（写权限留主人验收） |
| 4 | 公开知识/设定 | fatfish_lore | `fatfish_core` lore + KB | 复用自有 | 待接 |
| 5 | B 站只读资料 | fatfish_bili | `dsh-plugin-bilibili` 0.2.4 + bili-cli 0.6.0 | 复用社区 | 已就绪（只读） |
| 6 | B 站运营（推荐/互动/动态） | fatfish_bili | `dsh-fatfish-life` bundle | 复用自有 | 待接（执行器未迁完） |
| 7 | TTS 语音 | fatfish_voice | `fatfish_core/tts.py` + MCP `tts_speak` | 复用自有 | 待接出口（P3.2 已验合成） |
| 8 | STT 转写 | 旧 SenseVoice | onebot 桥 `stt.js` / `dsh-voice` ASR | 复用社区 | 待接 |
| 9 | 表情包图库 | meme_manager | `fatfish_core/gallery.py` + MCP 5 工具 | 复用自有 | 已就绪（164 张校验通过） |
| 10 | Steam 查询 | fatfish_steam | `fatfish_core/steam.py` + MCP | 复用自有 | 已就绪 |
| 11 | Steam 促销追踪 | SteamSaleTracker | 无社区件，薄适配 | 待适配 | 未开始 |
| 12 | 联网搜索 | anysearch | **DSH 原生 web_search** | 原生覆盖 | 已具备 |
| 13 | 主动消息 | proactive_chat | `dsh-routines` / 原生 schedule | 复用社区 | 未开始 |
| 14 | 群风格学习 | self_learning + fatfish_style | `fatfish_core` 风格模块 | 复用自有 | 待接 |
| 15 | 生活日记/动态 | fatfish_life | `dsh-fatfish-life` | 复用自有 | 部分就绪 |
| 16 | 视频创作 | fatfish_story | Updream + fatfish_video | 保留独立 | 保留（投稿需成片确认） |
| 17 | 离线兜底 | fatfish_offline | `fatfish_core/local_llm.py` | 复用自有 | 已就绪 |
| 18 | 情绪 CoT | emotionai | 人格 preset 已覆盖 | 原生覆盖 | 建议不迁 |
| 19 | Token 控制 | token_controller | DSH 原生 token-meter + 模型选择 | 原生覆盖 | 建议不迁 |
| 20 | QQ 空间 | qzone_ultra | 社区无，薄适配 HTTP | 待适配 | 未开始 |
| 21 | Pixiv 图片 | pixiv_search | 社区无（`dsh-image-search` 是反向识图，不等价） | 待适配 | 低优先 |
| 22 | 网易云音乐 | cloudmusic | `dsh-netease-island` 仅状态挂件 | 待适配 | 低优先 |
| 23 | 电子书 | ebooks | 社区无 | 待适配 | 低优先 |
| 24 | 漫画 | jm_cosmos | 社区无 | 待适配 | 低优先 |
| 25 | 内部验收 | fatfish_acceptance | 不迁（测试用途） | — | 不迁 |

## 三、执行顺序

1. **P-A QQ 通道切换**（#1）：把 `prepared-onebot` 装进 desktop profile → 隔离验收 → 仅在验收通过且用户确认后改 NapCat 指向；切换时防看门狗拉起旧服务。
2. **P-B 出口打通**（#7/#8/#9/#4）：最终回复 → 媒体决策 → TTS/选图 → OneBot 出口 → 真实回执；落实失败保原文、语音成功只发语音、临时文件回收、会话隔离。
3. **P-C 运营执行器**（#6/#13/#14/#15）：按主方案逐项迁，保留原开关、暂停、时间条件与不盲重发。
4. **P-D 长尾**（#11/#20/#21/#22/#23/#24）：逐项确认「要或不要」，不要的直接从清单移除，避免为低价值能力续写维护成本。

## 四点五、P-A 第一轮：隔离验收已通过（2026-10-29）

`prepare_dsh_control.py` → `prepare_dsh_onebot.py --pack` → `dsh_native_smoke.py` 三步已跑通，
归档 `dsh-fatfish-life-0.1.0-7b871dc8933c.tgz`、`fatfish-onebot-0.9.6-1ee53c49c782.tgz`。

**结果**：`ok=true`，15 项原生检查全通过，`bridgePluginActivated=true`，4 次本地 mock 模型调用，
`paidRequests=0`、`realPlatformSends=0`。报告 `outputs/dsh-migration/native-smoke/report-1793267250302054100.json`。
检查项覆盖：控制包生效、配置可见且实时、原生 peer 解析、带鉴权 loopback OneBot、忙时零模型调度、
真实传输戳一戳、非主人命令不触发控制路由、主人命令可用、真实 Agent 作用域工具被拦截、
完整人格进入请求、生成中静默/工作窗口拦截晚投递、402 不外泄、缺人格不降级。

**环境约束（新增记录）**：在受限文件沙箱下，工作区外（`D:\pnpm-store`、`D:\dsh`、`C:\Temp`）的 SQLite
无法取得文件锁，pnpm 的 store 索引打不开，导致 `dsh plugin` 安装失败并报 `unable to open database file`。
这不是插件缺陷。`scripts/dsh_native_smoke.py` 现支持 `FATFISH_SMOKE_STORE` 把 store 指到可写路径；
本轮使用 `outputs/dsh-migration/native-smoke/.pnpm-store`，并在换了 store 后清理旧 `profiles/` 目录
（否则 pnpm 报 `ERR_PNPM_UNEXPECTED_STORE`）。生产装插件不受此影响——它由宿主进程执行，不经过该沙箱。

**本轮未做**：未装生产 desktop、未改 NapCat 指向、未停 AstrBot、未发真实 QQ 消息。

## 四、边界（沿用既有授权，不因迁移放宽）

- 主人称「老大」，其他人老板/客户；语气与身份按现有核心卡，不因换引擎改人格。
- 完整会话隔离：平台 + 账号 + 适配器 + 群/私聊；私人记忆不进公开知识库。
- B 站只读标题/标签/简介/已有字幕/评论；**不抽帧、不下载音视频、不自动转写**。
- 视频统一 Updream；投稿须具体成片预览与老大确认。
- 凭据只留本机，不输出、不提交、不进聊天。
- 语音概率 15%、表情 35% 起、动态 20% 起等基线不改；DSH 管理默认静默。
- 停用 AstrBot 前保留冷备份；回退核对新增数据，不整库倒退。
