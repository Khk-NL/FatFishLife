# 养鱼家族插件：数据互通现状与整合方案

采样：2026-10-30 04:55–05:05（Asia/Shanghai）
方法：读 profile `cordis.patch.yml`、各包 `package.json` / `cordis.patch.yml` / `lib`，读实际落盘文件。运行时条目不可用 CLI 校验（`--dump-config` 被拒），见文末。

## 一、实测到的数据落点

| 数据 | 落盘位置 | 写者 | 读到什么 |
|---|---|---|---|
| 余额 / 今日花费 / 历史 / 逐次事件 | `~/.dsh/.dshw-usage.json` | dsh-whale-widget（`accounting.mjs`） | `lastBalance: 17.52`、`todayUsage: 6.56`、history 10-29/10-30、每回合 cost+tokens |
| 回合序号 | `~/.dsh/.dshw-turn.json` | dsh-whale-widget | `seq: 124` |
| B站分身会话 | `~/.dsh/whale-session.json` | dsh-whale-widget | `personaHash`、`startedAt`、`deliveredAt` |
| 作息 / 醒来窗口 | `~/.dsh/whale-night.json` | dsh-whale-widget | `schema 2`、`wakes`、`usedCount`、`22:11` 落在 `20:00–24:00` 窗口 |
| B站凭据 / 人设 | `~/.bili-ai/credentials.json`、`~/.bili-ai/persona.md` | dsh-bili-whale（登录）/ `scripts/sync_persona_dsh.py`（人设） | mid 3546899328010912、persona 由 core.md 生成 |
| 记忆 | `D:/Code/Apps/AstrBot/data/plugin_data/astrbot_plugin_fatfish_memory/memory.db`（2.43 MB，mtime 10-29 19:02） | MCP `mcp-fatfish-memory` | recall/remember/meme/tts/steam/bili 工具 |
| 知识库 | `~/.dsh/knowledge-base/kb.sqlite` | dsh-knowledge-base | `kb_*` 五个工具 |
| 笔记 | Obsidian vault | dsh-obsidian | `obsidian_*` 工具 |
| 人设（运行时） | profile patch `preset-apple-le` 的 `prefix`（约 4807 字符）+ `apple-social` preset | `sync_persona_dsh.py` | QQ 桥与 Web 会话共用 |
| 定时任务 | `dsh/control/schedule.mjs`（12:30 / 20:30 / 21:00 / 23:50）+ `data/dsh/schedule-state.json` | fatfish-control | 已真实触发 3 类 |
| 群聊归档 | `~/.dsh/integrations/dsh-im/group-history.sqlite` | dsh-im | 群历史检索工具 |

## 二、重复与互补（取长补短）

| 功能 | 谁在做 | 判断 |
|---|---|---|
| 余额显示 | whale-widget 自己查 DeepSeek（`balanceMode: 'api'`，`balanceSource: 'account' \| 'apikey'`，无 API 时退化为按事件估算）＋ dsh-balance-meter 提供 `/api/balance` | **互补但不通**：whale 按回合 token 记账（今日 6.56），meter 查官方账号余额。两者都不读对方，数值口径不同 |
| 桌宠 | dsh-pet 与 dsh-whale-widget 都是右下角常驻 | **冲突**：两个同时开就是抢位置 |
| 记忆 / 知识 / 笔记 | memory.db + kb.sqlite + Obsidian 三套独立存储 | **不通**：一次提问只能命中其中一处 |
| 作息 | whale-night（醒来窗口）＋ fatfish-control 定时（4 个点）＋ policy 峰时（9–12、14–18） | **三处各写一遍**：同一件事三个真相源 |
| 人设 | core.md 是单源，但 preset prefix、B站 persona.md、whale `personaHash` 三处派生 | 已由 sync 脚本统一；差一步：sync 后没刷新 whale 的 personaHash |
| 表情 / TTS | MCP 的 meme_find / tts_speak（data/memes 163 张、outputs/secrets/minimax.env）；whale 自己也要显示 | 资源已共用，入口两个 |

## 三、整合建议（按成本分三档）

### 档 1：配置级（不动代码）
1. whale-widget 的余额源显式固定为官方 API，别再走估算——避免和 balance-meter 的官方值打架。
2. dsh-pet 与 dsh-whale-widget 二选一（建议留 whale：它有余额、作息、表情、B站分身四件事）。
3. `sync_persona_dsh.py` 末尾顺带刷新 `whale-session.json` 的 `personaHash`，人设一改三处同步。

### 档 2：薄胶水（每项百来行）
4. **统一检索**：加一个 `fatfish_recall_all(query)`，一次查 memory.db + kb.sqlite + Obsidian + 群聊归档，带来源标签。这是"数据互通"最划算的一步——不用迁库，先让一次提问能命中四处。
5. **作息表合一**：一份 `data/dsh/rhythm.yml`（醒来窗口 / 定时点 / 峰时），fatfish-control 读它，whale-night 与 `schedule.mjs` 都从它派生。
6. **成长写入口**：把 `fatfish_core/growth.record_capability` 接到 MCP，DSH 侧才有地方记录经历（现在 82 条停在 10-28，因为调用方全在已停用的 AstrBot 插件里）。

### 档 3：迁库（贵，先别做）
7. kb.sqlite 与 memory.db 合并、Obsidian 全量导入。数据量不小（memory.db 2.4 MB、kb 条目未知），收益不如档 2 的检索层，等档 2 跑一段时间再决定。

## 四、上一轮配置修复的现状

| 插件 | 现状 | 处置建议 |
|---|---|---|
| `@loserfox/distill` | 包、`dsh.bundle.patch`、profile 行（`minUserMessages: 10`）都在；04:40 采样无运行时条目 | 保留；验证靠"攒够 10 条消息后 `~/.agents/skills/*/SKILL.md` 是否出现" |
| `dsh-balance-meter` | 同上，无运行时条目 | 保留（whale 的官方余额可改由它供） |
| `dsh-context-doctor` | 同上，无运行时条目 | 保留；验证靠设置页是否出现审计面板 |
| `dsh-plugin-wallpaper-engine` | 只在 dependencies，没进 bundles；补丁要 8 行 + 4 个子包 `wallpaper-engine-*`（`webwallgl`、`x11` 等） | **建议摘掉**：与 pet 功能重叠，装它要拉一堆子包 |
| `dsh-knowledge-base/web` | 条目在，`fiberPhase: failed` | 工具侧可用（`kb_query` 正常），面板单独修 |
| `dshmarket` 1.73.1 → 1.73.3 | 待升级 | 升级要先退出应用（运行中占目录，会 EPERM） |

宿主对"补丁行挂不上"是静默的，`dsh.cmd --dump-config` 又拒绝 desktop profile（"managed exclusively by the Electron application"），所以运行时条目只能靠插件自己的产物反推——这是目前验证手段的天花板。

## 五、待定
1. 桌宠留 whale 还是 pet。
2. 记忆/知识走"统一检索"（档 2-4）还是"迁库合并"（档 3）。
3. 作息表是否合并成一份 `rhythm.yml`（档 2-5）。

## 12. 定时业务与主动开口（2026-10-30 05:00 落地）

- **数据出口打通**：桥新增 `ctx.provide('dshOnebotTransport', {connected, selfId, sendText, sendSegments})`（`scripts/patch_transport.py`，锚点唯一、已备份 `index.js.bak-transport`），fatfish-control 通过 `dsh/control/transport.mjs` 拿到发送能力，不再依赖 MCP 才能说话。
- **四个定时任务接了真业务**（`dsh/control/business.mjs`）：
  - `bili-recommend` 12:30 / 20:30：`bili feed recommend -n 14 --unseen` → `ops.selectRecommendations`（关键词 + 去重 + 上限 2）→ DeepSeek 各写一句 ≤40 字理由 → 发一条 → 写 `task-state.json.seenBvid`（上限 300）。
  - `bili-inbox`（备用 kind）：未读摘要，空则不发。
  - `bili-study` 21:00：20 条标题 → 模型抽 5 个说法 → 追加 `data/dsh/style-learned.jsonl`（当前只记录，尚未注入对话提示词）。
  - `diary` 23:50：`hub day-digest/mood-get/style-terms/journal-recent` → 模型写 150–300 字 → `hub journal-write` → 写 `runner.diaryDir/<day>.md`（Obsidian，frontmatter `tags: [日记, 苹果乐]`）→ 给主人发 120 字摘要。
- **主动开口**（`dsh/control/proactive.mjs`）：每 5 分钟判断一次，闸门顺序 `disabled → busy → quiet → gap → cap → roll`；默认 `basePercent 8`、`minGapMinutes 150`、`dailyCap 3`、安静时段 `00:30–07:30`，只在 `runner.ownerChat`（默认由 `identity.ownerId` 推出）说话，不进群；发完写 `proactive-state.json` 并把心情 +0.05。
- **配置单一真相源**：`tasks`（默认 `schedule.mjs` 的 TASKS）、`runner`、`proactive` 三段进 `fatfish-control` 的 Config 且标 `volatile`，可在设置卡里改；`runner.enabled=false` 时到点只记录不执行。
- **中枢 CLI**（`fatfish_core/hub.py` + `dsh/service/fatfish_hub_cli.py`，python 子代理交付）：`mood-get/mood-nudge/lore-search/lore-context/journal-write/journal-recent/day-digest/style-terms`，MCP 侧同名 8 个工具；写入口在两处都校验 `FATFISH_HUB_WRITE=1`（CLI 守卫本轮补上，profile 的 MCP env 已加该变量）。
- **style_terms 质量修复**：`fatfish_core/learning.py` 原来拿单字集合去比对 2–4 字 token，等于没过滤；新增 `STOP_TERMS` 词表 + 全虚词片段与虚词边界过滤，真实库 7 天结果从「这个/什么/不是/一个」变为「老板/苹果/能力经历/成功…」。
- **验证**：node 81 项全过（新增 `dsh/tests/business.test.mjs` 12 项：格式化、推荐筛选与去重、无目标不外发、日记写文件+记忆库+摘要、未知任务报错、跨零点忙碌窗口、主动开口六道闸门）；python `test_dsh_*.py` 56 项、`test_hub` 26 项、`test_hub_cli` 4 项、`test_unified_recall` 8 项全过；真网真模型干跑一次（`outputs/agent/dry-run-business.mjs`）：推荐选中 BV1vyxE6LEMq、学到 4 个说法、日记 165 字写入 `outputs/dry-run-diary/2026-10-30.md`。
- **尚未验证**：宿主重启后 transport provide 是否生效、定时任务真实发送、主动开口实际触发——这三项依赖 05:03 的重启（计划任务 FatFishRestartDSH）。
- **已知限制**：`style-learned.jsonl` 尚未接进对话提示词；日记摘要外发依赖 `runner.ownerChat`；`bili feed recommend` 偶发候选不足（本次 11 条里只 1 条命中关键词）。
