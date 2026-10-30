# 六件套核对与全流程状态（2026-10-30 傍晚）

> 起因：朋友建议装「一个桌宠、一个记忆插件、一个上下文查看、一个插件市场、一个QQ桥接、一个snowluma」。
> 本文只写有证据的部分，无证据的标「未验证」。

## 一、六件套对照

| 朋友说的 | 对应东西 | 状态 | 证据 |
| --- | --- | --- | --- |
| 桌宠 | `dsh-whale-widget@0.4.2`（右下角小鲸鱼） | 已装 | profile `bundles` 第 12 项；`cordis.patch.yml` 无告警 |
| 记忆插件 | 自建 `mcp-fatfish-memory` + `fatfish_core.hub` + `recall_all` 四源检索 | 已装并通 | `mcp__fatfish__stats` 返回 persona 1959 字 / 候选 199 / 已确认 12；`recent` 能取回群聊消息 |
| 上下文查看 | `dsh-context@0.78.0` + `billion-context@0.1.209` | 已装，可用 | 客户端 inject 6 项全部可解析；本会话的 `compress/acp_status` 就由 billion-context 提供 |
| 插件市场 | `dshmarket@1.73.1` + `dsh-find-plugin` | 已装 | 客户端 inject 3 项可解析；`find_dsh_plugin` 实测有返回 |
| QQ 桥接 | `dsh-onebot-qq@0.9.6` + NapCat（反向 WS） | 已装并跑通 | `qq-trace.jsonl` 15:36:00 inbound → 15:36:02 outbound（真实往返）；8643 由宿主进程 54224 监听 |
| snowluma | SnowLuma（独立协议端，不是 DSH 插件） | **未装**，且不建议现在装 | 见第三节 |

## 二、补充：真的坏掉的插件（客户端 peer 缺失）

rc.3 的包里**没有** `@deepseek-ai/dsh-client-runtime`、`@deepseek-ai/dsh-client-store`、`@deepseek-ai/dsh-client-ui-slots`
（在 `app.asar` 索引里也搜不到）。所以下面这些插件的 UI 部分一定加载失败：

| 插件 | 缺的 peer |
| --- | --- |
| `dsh-knowledge-base@0.1.5`（知识库面板） | `dsh-client-runtime` |
| `dsh-context-doctor@0.7.2`（上下文体检面板） | `dsh-client-store`、`dsh-client-ui-slots` |
| `dsh-better-sidebar@0.28.2`（侧边栏） | `dsh-client-ui-slots` |
| `@xmanrui/dsh-im@5.7.0` | `dsh-client-runtime`、`dsh-client-ui-slots` |

工具侧不受影响：`kb_list` 实测 28 条、`kb_query` 正常。

复核脚本：`outputs/agent/check-client-peers.mjs`（只读，扫 profile 里每个插件的 `dsh.client.inject` 并逐个解析）。

## 三、snowluma 是什么，为什么先不动

事实（来源：<https://github.com/SnowLuma/SnowLuma>、<https://snowluma.github.io/zh/docs/guide/introduction>）：

- SnowLuma 是**面向 NTQQ 的远程协议框架**，通过 native addon 注入正在运行的 `QQ.exe`，把 QQ 原生会话转成 **OneBot v11**（HTTP / WS / 反向 WS / HTTP 上报），自带 WebUI（默认 5099）与 `@snowluma/mcp`。
- 它和 NapCat 是**同一层的东西**：都 hook 本地 QQ 客户端，对外都讲 OneBot v11。换句话说，它替换的是 NapCat，不是 DSH 插件。
- 硬约束：hook 与 QQ 版本严格对齐（社区文档点名当前对齐 `QQ 9.9.28-46928`，装更高版本 hook 失效）；要冻结 QQ 自动更新；必须与 QQ 同用户同权限运行；**同一个 QQ 号不能同时接两个协议端，会互相踢下线**。

补充事实：默认端口 OneBot HTTP `3000`、OneBot WS `3001`、WebUI `5099`；鉴权 `Authorization: Bearer <token>` 或 `?access_token=`；
Windows 发行包是 `SnowLuma-<TAG>-win-x64.zip`（完整版内置 Node）与 `-lite`（需 Node ≥22.13）；自带 `@snowluma/mcp`，能让支持 MCP 的客户端直接调 OneBot action。

结论：换 SnowLuma = 换协议端，收益不明、风险明确（重新扫码登录、QQ 版本绑定、和 NapCat 互踢）。
现有 `NapCat + dsh-onebot-qq` 已实测收发正常，**保持现状**。真出问题（比如 QQ 升级后 NapCat 挂了）再迁：
把 NapCat 的反向 WS 客户端 `ws://127.0.0.1:8643/ws` 原样搬到 SnowLuma 的反向 WS 客户端配置即可，DSH 侧一行不用改（token 仍是 `9a5603f1eb82c47d`）。

## 三·五、记忆插件为什么"看着在、其实写不进去"

查 `~/.dsh/profiles/desktop/cordis.patch.yml` 第 45 行，MCP 记忆服务的环境变量是
`FATFISH_SERVICE_READONLY: '1'` —— 代码里 `_readonly()` 一票否决，`remember` / `review` / `extract`
全部直接返回 `{"ok": false, "error": "服务以只读模式启动"}`。

后果：候选记忆堆到 **199 条没人审**、已确认只有 12 条；她能检索历史，但记不住新东西。

已改成 `'0'`（备份 `cordis.patch.yml.bak-readonly-*`），**下次重启后生效**。
风险提示：`FATFISH_MEMORY_DB` 指向 `D:\Code\Apps\AstrBot\data\plugin_data\astrbot_plugin_fatfish_memory\memory.db`，
这个库原来是 AstrBot 的；AstrBot 已停用，现在只有 DSH 在写，不会互踩，但库里混着 AstrBot 时代的数据。

社区同类插件对比（都不如现有栈，只作备选）：

| 包 | stars | 群隔离 | 依赖 | 结论 |
| --- | --- | --- | --- | --- |
| `x2it/dsh-memory-panel` | 1 | 无（全局 key） | 无，`~/.dsh/memory.json` | 最轻，只能存跨群通用事实 |
| `liuqingman/dsh-somni` | 0 | 无 | Python 侧车 + 可选 ONNX 向量 | 功能最全但 Windows 装起来最重 |
| `2540511/dsh-memory` | 1 | 按会话目录 | 无 | 面向手动粘贴，不适合 bot |
| `eteced/memoplus4dsh` | 1 | 无 | 每轮 LLM 抽取（烧额度）+ 135MB ONNX | 大炮打蚊子 |
| `rickwindman/dsh-destinywind-memory` | 0 | 无，且全库注入系统提示 | `node:sqlite` | 多群必串味，排除 |

唯一的「按群隔离 + 纯本地 FTS5 + 无外部向量服务」就是现有的 `fatfish_core/memory.py`（`memory_fts` 有 `group_id` 列，工具 `search(query, group_id)`）。

## 四、全流程实测（今天）

| 链路 | 结果 | 证据 |
| --- | --- | --- |
| QQ 私聊往返 | 通 | `qq-trace.jsonl` 15:36:00 inbound / 15:36:00 dispatch / 15:36:02 agent / 15:36:02 outbound |
| 主动开口（生成+发送+记心情） | 通 | `mcp__fatfish__mood_get` 返回 `reason="主动说了句话"`、`updated_at=1793343534`（15:38:54）；`proactive.mjs:115` 只在发送成功后才写心情 |
| 定时器 | 在跑 | `scheduler-heartbeat.json` 每 30 秒更新；`control-mount.json` = `{"stage":"done","tasks":4}` |
| 语音合成 | 通 | `tts_check` → `synthesis_verified: true` 之前是 false；`tts_speak("老大，语音通了。")` 返回 `outputs/dsh-media/tts/38e029f2.../tts.wav`（107606 字节，speech-2.8-hd） |
| 表情包 | 通 | `meme_random` 返回 `data/memes/能天使/IMG_1792759626124.png.jpg` |
| 群聊 / 表情 / 语音真发到 QQ | 未验证 | 需要在 QQ 里实际触发；媒体白名单 12 个工具已就位，`extraMediaRoots` 含 `outputs/dsh-media` |
| 20:30 推荐任务 | 未验证（待今晚） | 已挂 20:35 的核对提醒 |

## 五、待办与建议（按优先级）

1. **升级 rc.3 → rc.5**（安装包已下到 `outputs/downloads/deepseek-harness-0.2.1-rc.5-win-x64.exe`，289 MB）。
   预期收益：补齐上面 4 个客户端 peer，知识库/上下文体检/侧边栏三个面板恢复；顺带解决 `distill`、`context-doctor`、`balance-meter` 的版本门禁。
   风险：升级会关掉应用、结束当前会话；升级后 `@deepseek-ai` 的 junction 指向旧版本包，必须重跑解包。
   已备好一键脚本：`outputs/agent/upgrade-to-rc5.ps1`（停应用 → `/S` 静默装 → 重新解包 app.asar → 重建 junction → 重启），**在应用外**的 PowerShell 里执行。
2. 记忆插件不需要再装：现有 `mcp-fatfish-memory` 已覆盖 persona/候选/群聊/知识库/Obsidian 四源，且带写守卫。
   社区里唯一的同类是 `dsh-viya-memory`（2★，Markdown 卡片进 Obsidian），功能面比现有栈窄，暂不引入。
3. 语音/表情真发要在 QQ 里点一次才能算验证（发「发条语音」给她即可）。
4. 今晚 20:30 / 21:00 / 23:50 三个定时任务是「业务真发」的第一次考试，结果看 `data/dsh/schedule-state.json` 的 `results`。

## 六、这次踩的坑（写给接手的人）

- **不要在应用运行时修 profile 或跑探针进程**：两者共用同一份 `node_modules` 与 `data`，探针会抢 8643 端口（15:39 的 `EADDRINUSE` 就是它），改 `package.json` 会让应用整体重载（`unlag-reload.log` 有 15:32:59 / 15:39:06 / 15:42:46 三次），重载会杀掉正在跑的会话 —— 用户看到的就是「闪退」。
- Windows 事件日志里**没有** DeepSeek Harness 的崩溃记录，说明不是 OS 级崩溃。
- 需要看插件挂载失败的真实原因时，用独立进程：`dsh.cmd --profile probe --no-open --port 0`，它会打印 `N entries did not activate` 和每条的 pending/failed 原因。
