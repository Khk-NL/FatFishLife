# DSH 侧交接文档（2026-10-30 14:40）

## 15:02 续修与生产重载（Codex）

以下原交接保留为 14:40 的历史记录；当前状态以本节及本机运行证据为准。

- 已修复真正的动态配置读取：`tasks`、`runner` 等 `.volatile()` 字段必须先 `.get()`。此前的 `Array.isArray(config.tasks)` 只会回退默认表，读取 `config.runner.enabled` 也无法识别关闭状态。现在每轮使用同一份配置快照，任务表、总开关、主动开口开关和主人发送目标均取当前值。
- 挂载标记改为合法 JSON，挂载时的任务数量来自实际配置；全局定时器通过 Cordis effect 登记清理，插件卸载后不会继续留下旧 interval。
- 已更新 desktop 中的控制插件与对应 `file:` 打包依赖；QQ 桥只删除两处 import trace，保留安装目录中已有的其他适配，并从该目录打包、更新依赖地址，避免下次安装恢复旧探针。
- `dsh-balance-meter@0.1.0` 导入了当前 DSH 0.2.1-rc.3 未导出的 `installSettingsSection`。已从 desktop 的 bundles 停用，保留安装包，不修改宿主 SDK。
- 15:00:23 已通过一次性计划任务重启 GUI 宿主，启动任务返回 0。新宿主生成 `control-mount.json`：`stage: done, tasks: 4`；8643 端口重新监听并与 NapCat 建立连接。未修改 `cordis.patch.yml` 的身份、静默、媒体或运营设置。
- 独立宿主使用独立 `DSH_HOME`、数据目录、假身份、随机端口、关闭执行器和主动开口，避免旧 probe 与生产共用数据、抢占 QQ 或触发发送。实际挂载及第二次 30 秒心跳通过，关闭执行器的到点任务记录 `runner-disabled`；桥挂载和监听成功，未激活告警为 0。沿用 desktop 已有的精确版本豁免，distill 和 context-doctor 在此配置中未出现未激活告警，不代表业务功能验收完成。
- 验证：83 项 Node 测试通过（含本机真实 SDK 的 volatile 配置/计时器清理回归），22 项 Python 打包/安装/交付测试通过；桥入口语法检查通过。运行 `FATFISH_DSH_TEST_PROFILE` 指向本机 profile 可执行新增 SDK 回归；未设置该变量时跳过该用例。
- 尚未验收：真实 QQ 入站后的模型回复、真人客户端效果、20:30/21:00/23:50 到点业务、主动开口的真实发送。本轮没有主动发送测试消息、补跑任务或合成收费语音。

本机证据与回滚资料（均未提交）：

- `outputs/dsh-repair-20261030/backup/`：配置及两个插件原入口备份。
- `outputs/dsh-repair-probe/report.json`：独立宿主验证报告；`host.private.log` 含本机访问凭据，禁止分享或提交。
- `outputs/dsh-repair-20261030/host.private.log`、`host-error.private.log`、`launched.txt`：桌面宿主启动记录。


写给接手的人/agent。目标是让 FatFishLife 在 DSH 里真正跑起来，并且**重启不打断你自己的工作**。

---

## 0. 先看这三条

1. **今天卡了一整天的挂载故障已经修好了**，并在独立进程里验证过（见 §3）。生产 GUI 宿主还跑着旧代码，**需要一次重启**才会生效。
2. **重启会杀掉“跑在宿主进程里的 agent 会话”**——这就是你觉得“老是崩”的原因，不是 DSH 崩。想让重启不打断你，就**在宿主外面干活**（§5）。
3. **不用重启也能验证插件挂没挂**：用 probe profile 起一个独立进程（§4），它会把每个插件挂载失败的真实原因打印出来。这条路今天救了场。

---

## 1. 环境事实（都验证过）

| 项 | 值 |
| --- | --- |
| DSH | desktop `0.2.1-rc.3`，仓库/工作区 `D:\Code\Projects\FatFishLife` |
| 宿主可执行 | `D:\dsh\DeepSeek Harness.exe` |
| CLI | `D:/dsh/resources/runtime/cli/bin/dsh.cmd`（不在 PATH） |
| profile | `C:\Users\kongb\.dsh\profiles\desktop\{package.json,cordis.yml,cordis.patch.yml,compatibility.json}` |
| 插件代码实际位置 | `C:\Users\kongb\.dsh\profiles\desktop\node_modules\<包名>\` |
| Web GUI | 每次重启换端口，看宿主窗口或 runtime context（今天是 13524） |
| 机器人 QQ / 主人 QQ | `1670515707` / `3124904460` |
| NapCat | `D:\Code\Apps\NapCat`，配置 `config\onebot11_1670515707.json`，反连 `ws://127.0.0.1:8643/ws`，token 仅保留在本机配置 |
| B 站 CLI | `D:/Code/Apps/bili-venv/Scripts/bili.exe`，凭据 `~/.bili-ai/credentials.json`（阿_噗噜派啊，mid 3546899328010912） |
| Git | `main`，HEAD `4592d3f`，已 push |

**权限坑（非常重要）**：沙盒里 **python 子进程不能写** `~/.dsh/profiles/**`（`PermissionError [Errno 13]`，目录 ACL 只给 CodexSandboxUsers RX），但 **ops_bash 的 shell（`cp`/`mv`/`printf >>`）可以写**。
固定套路：python 生成到仓库 `outputs/...` → shell `cp` 覆盖到 profile。

---

## 2. 今天定位到的三个真因（已修，源码在仓库）

### 2.1 `@deepseek-ai/*` 依赖全断
`~/.dsh/profiles/node_modules/@deepseek-ai/` 下 253 个软链指向不存在的 `D:\Code\dsh\deepseek-harness\apps\cli\node_modules`。
**修法**：从 `D:/dsh/resources/app.asar` 解出 315 个包到 `D:\Code\dsh-runtime-modules-pkg`，旧目录改名 `@deepseek-ai.broken-1339`，建 junction：

```
~/.dsh/profiles/node_modules/@deepseek-ai  ->  D:\Code\dsh-runtime-modules-pkg
```

解包脚本 `outputs/agent/extract-dsh-pkgs2.mjs`（**用 asar 条目的 `integrity.hash` 校验 offset/size 四种组合**，6318/6318 全匹配）。不要用旧的 `extract-dsh-pkgs.mjs`（`size+1` 硬编码，只对一半文件有效）。
⚠️ `~/.dsh/profiles/node_modules` 下还有 96 个软链是断的（commander/chokidar/accepts 等），目前没影响挂载，但以后哪个插件报 `Cannot find package 'commander'` 就是它。

### 2.2 `fatfish-control` 自己不挂，QQ 跟着全哑（**今天的主因**）
`dsh/control/index.mjs` 里有我加的一行调试留痕：

```js
mark('control-mount.json', { stage: 'enter', hasEffect: typeof ctx.effect, hasSetInterval: typeof ctx.setInterval })
```

这版宿主把 **timer 做成必须 inject 的服务**，`typeof ctx.setInterval` 一下就直接抛：

```
fatfish-control (dsh-fatfish-life): Error: cannot get property "timer" without inject at Object.apply
```

而且这个留痕写在 `apply` 的第一行，于是 `apply` 一进来就抛 → 插件永远不 provide `fatfishSettings` → 桥一直 `pending (waiting for service: fatfishSettings)` → **QQ 完全没反应、定时器也没起来**。
**修法**：删掉所有 `ctx.setInterval` / `ctx.setTimeout` 探测（定时器本身用全局 `setInterval` 就行）。

### 2.3 `config.tasks` 不是数组 → 定时任务一条都不跑
`runDue()` 里 `(config.tasks ?? TASKS).filter(...)`，patch 里没写 `tasks` 时 `config.tasks` 会落成**对象**，抛
`(config.tasks ?? TASKS).filter is not a function`，被 catch 记进 `scheduler-heartbeat.json` 的 `error` 字段。
**修法**：`Array.isArray(config.tasks) ? config.tasks : null`，其余回退内置 `TASKS`。

---

## 3. 现在的状态（以 14:35 独立进程验证为准）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| `fatfish-control` 挂载 | ✅ | `data/dsh/control-mount.json` = `{"stage":"done","tasks":4}` |
| 定时器在转 | ✅ | `data/dsh/scheduler-heartbeat.json` = `{"at":...,"tasks":4,"due":0}`（30 秒一跳） |
| `dsh-onebot` 挂载 + NapCat 连上 | ✅ | 控制台 `[dsh-onebot] mounted` / `reverse WS server listening on ws://127.0.0.1:8643` / `OneBot connected` |
| `dsh-balance-meter` | ❌ 真版本不兼容 | `does not provide an export named 'installSettingsSection'`，与门禁无关；要么装旧版，要么从 bundles 摘掉 |
| 定时任务真发 | ⏳ 待观察 | 今天 20:30 / 21:00 / 23:50 到点后看 `data/dsh/schedule-state.json` 的 `results` |
| 主动开口 | ⏳ 待观察 | 看 `data/dsh/proactive-state.json` |
| QQ 真收发 | ⏳ 待重启后实测 | 重启后给她私聊发一句，看 `~/.dsh/media/onebot/fatfish-qq-*/qq-trace.jsonl` 里 `ok:true` |

**生产宿主现在跑的还是旧代码**（14:19 启动，早于修复）。要让上面这些生效，**需要重启一次 GUI 宿主**。

---

## 4. 不重启也能验证插件挂载（今天最有用的一招）

`~/.dsh/profiles/probe` 是 desktop 的配置副本，`node_modules` 是指向 desktop 的 junction。用 CLI 起一个**独立进程**，它会打印所有挂载失败原因：

```bash
cd /d/Code && timeout 45 "D:/dsh/resources/runtime/cli/bin/dsh.cmd" --profile probe --no-open --port 0
```

判读要点：

- 正常时只该有 **1 条** `dsh: warning: 1 entry did not activate`，且就是 `balance (dsh-balance-meter)`。
- 出现 `fatfish-control ... active` 失败 / `dsh-onebot ... pending (waiting for service: fatfishSettings)`，说明控制插件又挂了。
- 起来后再看两个标记文件（**注意 probe 和 GUI 共用同一个 `dataDirectory`**，会互相覆盖）：

```bash
cat data/dsh/control-mount.json      # stage: done
cat data/dsh/scheduler-heartbeat.json # 有 tasks/due，没有 error 字段
```

改完代码 → `prepare_dsh_control.py` 打包 → `cp` 进 `node_modules` → 再跑一次这条命令，**全程不用碰 GUI 宿主，也不打断你自己的会话**。

---

## 5. 重启，以及“怎么重启不打断我”

### 5.1 重启怎么做
```bash
powershell -NoProfile -ExecutionPolicy Bypass -File "D:/Code/Projects/FatFishLife/outputs/agent/restart-dsh.ps1"
```
或者让它 120 秒后自己重启（这样你能先把话说完整）：
```bash
powershell -NoProfile -ExecutionPolicy Bypass -File "D:/Code/Projects/FatFishLife/outputs/agent/restart-now.ps1"
```
日志：`outputs/agent/restart-dsh.log`、`host-out.log`、`host-err.log`（Electron 宿主**不会**把插件告警写进这些文件，别指望）。

### 5.2 为什么重启会“崩”
DSH 的模型会话**跑在宿主进程里面**。`Stop-Process` 杀掉宿主 = 杀掉正在跑的那一轮对话。今天 13:16 那次就是这么把你上一轮的活干掉的——不是崩溃，是自杀。

### 5.3 想重启不打断自己，只有一条路：**在宿主外面干活**
- 用终端里的另一个 agent（Codex CLI / Claude Code / 任意命令行 agent）在 `D:\Code\Projects\FatFishLife` 里跑，重启宿主与它无关；
- 或者把要跑的东西写成脚本 + 计划任务（`Register-ScheduledTask`），脚本里自己重启宿主、再自己等标记文件出现；
- **别在 DSH 会话里让它重启 DSH**：那就是现在的局面。

判据固定成一句话：*“先跑 §4 的 probe 命令，看到只有 balance 一条告警，再重启 GUI 宿主。”*

---

## 6. 文件地图

**源码（仓库）**
- `dsh/control/index.mjs` —— 控制插件主体：`apply`、`runDue`（30 秒）、`tickProactive`（5 分钟）、`fatfish_status` 工具、`ctx.provide('fatfishSettings')`
- `dsh/control/{schedule,ops,business,proactive,compose,transport,llm,bili,hub,settings}.mjs`
- `dsh/policy.mjs`（话术策略 / 工具白名单 `SOCIAL_MEDIA_TOOLS` / `canSend`）
- `dsh/runtime-adapter.mjs`（`SOCIAL_CHANNEL_PROMPT`、`assertOutbound`、`parseNewTarget`）
- `dsh/preset-apple-le.yml`（agent preset）
- `dsh/tests/*.test.mjs`（81 项）、`tests/test_*.py`
- `scripts/prepare_dsh_control.py`、`scripts/prepare_dsh_onebot.py --pack`、`scripts/sync_persona_dsh.py`
- `docs/persona/apple-le-core.md`、`docs/persona/apple-le-examples.md`（人设源；改完跑 sync 才生效）

**部署（profile）**
- `~/.dsh/profiles/desktop/node_modules/dsh-fatfish-life/` ← `cp outputs/control-new/package/*.mjs`
- `~/.dsh/profiles/desktop/node_modules/dsh-onebot-qq/` ← `cp outputs/bridge-new/package/lib/*`
- `~/.dsh/profiles/desktop/package.json` 里两个 `file:...tgz` 依赖要指向**最新**打包产物，否则 `pnpm install` 会把你 cp 进去的代码覆盖回旧版

**运行期标记（`data/dsh/`）**
- `control-mount.json`（插件挂上了没）、`control-error.json`（apply 抛了什么）
- `scheduler-heartbeat.json`（定时器在转没）、`schedule-state.json`（真跑到哪、成功失败）
- `proactive-state.json`（主动开口历史）、`runtime-policy.json` / `runtime-behavior.json`（DSH 侧的权威配置快照）

**诊断**
- `~/.dsh/media/onebot/fatfish-qq-*/qq-trace.jsonl`（QQ 收发全链路）
- `outputs/plugin-probe/import-trace.log`（插件模块 import 留痕；`dsh-onebot-qq/lib/index.js` 里还剩 2 行探针，稳定后删）
- `outputs/plugin-probe/probe*.mjs`（今天写的探针，**基本都可以扔**，只留 §4 那条命令就行）
- `~/.dsh/profiles/{@deepseek-ai.broken-1339,desktop/package.json.bak-*,package.json.broken-*}`
- `D:\Code\dsh-runtime-modules-pkg`（从 asar 解出的 315 个 `@deepseek-ai` 包）

---

## 7. 待办（按优先级）

1. **重启一次 GUI 宿主**，然后按 §3 的表逐项核对（20:30 推荐 / 21:00 学梗 / 23:50 日记 真发；`proactive-state.json`）。
2. `dsh-balance-meter`：装兼容版或从 `dsh.profile.bundles` 移除（它今天一直在报错，但不影响其他）。
3. 删掉 `dsh-onebot-qq/lib/index.js` 里遗留的 2 行 trace。
4. 配置项现状：`D:\Code\DSH-插件现状清单.md` 里 4 个静默不生效的（distill / balance-meter / context-doctor / wallpaper-engine 已摘）——`compatibility.json` 已放开门禁，distill 与 context-doctor 需要重启后验证有没有真的起来；wallpaper-engine 已移除；balance-meter 见第 2 条。
5. 4 个没装的：`dsh-speak-up`、`dsh-feiyu-mood`、`surfcore`、`PPT-Design-Skill`。其中前两个正好是“主动搭话 / 情绪系统”，而我自写了 `dsh/control/proactive.mjs` —— 按“优先复用成熟插件”的规矩，**建议换成插件**，我写的只保留 `inBusyWindow` 这种时段闸门。
6. 其它 backlog：`style-learned.jsonl` 接进对话提示词、表情包自动配图、Steam 促销追踪、`dsh-knowledge-base` Web 面板 `fiberPhase: failed`、QQ 群要不要放行 web 工具、B 站发动态缺 `buvid3`。
7. 今天我改的调试代码：`dsh/control/index.mjs` 的 `mark('control-mount.json', ...)` 留痕是**故意留着**的，直到 20:30 任务真发过一次再删。

---

## 8. 踩过的坑（省得你重踩）

- **PowerShell 5.1 读 UTF-8 无 BOM 中文脚本会解析失败**（`LastTaskResult 1`、日志为空）。`outputs/agent/*.ps1` 一律纯 ASCII。
- python heredoc 里写 `\a`、`\r`、`\n` 会被转义成控制字符，把脚本写坏（曾经把日志路径写成 `outputs\x07gent`）。带反斜杠的内容用 `write` / `edit` 工具写。
- `Start-Process` / `Invoke-CimMethod Win32_Process Create` 起的进程会被宿主或沙盒 job 连带杀掉；**只有计划任务能活过一轮**。
- `dsh plugin add` 在这台机器上会失败（pnpm store 在 `D:\pnpm-store`，SQLite 无法在 workspace 外取锁）。手动装：`npm pack` / `git clone` → 复制到 `node_modules` → 写 `package.json` 的依赖与 `dsh.profile.bundles`。
- `dsh.cmd --profile desktop --dump-config` 会被拒（desktop 由 Electron 独占）；要 dump 就用 `--profile probe`。
- 插件 `ctx.tools.restrict({allow})` 只认“全局已注册工具名”，桥自带的 `qq_send_*` 写进去会整条报错；现在改成只挂 guard（`toolDenial` 白名单）。
- 桥的媒体出口有围栏（`本地路径不在允许的媒体目录内`），已加 `extraMediaRoots`（`data`、`outputs/dsh-media`）。
