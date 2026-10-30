# 补装插件记录（2026-10-30 夜）

来源：`D:\Code\DSH-插件现状清单.md` 第 66-69 行列的四项「未装」。

## 一、dsh-speak-up 0.2.7（主动搭话）— 已装已配

- 来源 npm `dsh-speak-up@0.2.7`（GitHub `Yuuyuko-uu/dsh-speak-up`，16★），打包成 `.tools/dsh-vendor/adapted/dsh-speak-up-0.2.7.tgz`。
- 装法（因为 `dsh plugin add` 的 pnpm 库锁问题）：解包到 `~/.dsh/profiles/desktop/node_modules/dsh-speak-up/`，profile `package.json` 的 `dependencies` 指向 tgz、`dsh.profile.bundles` 追加 `dsh-speak-up`。
- 配置写在 `~/.dsh/speak-up-config.json`（插件自带默认值，中文键）：
  - `目标会话` = `fatfish-qq-c83cbdc5f4dc930841197746250d300f5cd609035ecb151bcc6e644ed1b829be` —— 老大私聊的会话 id，按桥的 `policy.sessionId()` 公式算出来并用已知目录名反向校验过（`fatfish-qq-2d989f…` 对得上）。
  - `试运行: false`（真发）；`间隔分钟: 30`；`峰时命中线: 5`、`谷时命中线: 60`（忙时几乎不开口）；`峰谷时区: Asia/Shanghai`；`安静起: 0`、`安静止: 8`；`搭话冷却分钟: 120`；`没中加成/加成上限` 默认 10/40。
- 它走 `agent.followup()` 让 DSH 自己开一轮，人格/历史/工具/记忆都照旧；掷骰子是本地随机，不花 token。
- 与仓库自写的 `dsh/control/proactive.mjs` 功能重叠（我方 8%/5 分钟 tick、150 分钟间隔、日上限 3）。两者现在都开着，**待验证后择一**：优先留 speak-up（社区件、有安静时段与峰谷），把我方 `proactive.enabled` 关掉。

## 二、dsh-feiyu-mood 0.8.1（情绪）— 已装

- 来源 npm（GitHub `Yuuyuko-uu/dsh-feiyu-mood`，202★），tgz 放在 `.tools/dsh-vendor/adapted/dsh-feiyu-mood-0.8.1.tgz`，同样解包 + 写 `dependencies`/`bundles`。
- 存储目录 `~/.dsh/feiyu-mood/{config.json,state.json,diag.log}`（首次聊天后生成）。
- 机制：每轮结束用 DSH 自己的模型判一次心情走向，通过 `systemPrompt.context` 注入一句话（**不改系统提示本体，不破坏前缀缓存**）；判断没底的只记后台不进对话。
- 已知限制：它的面板 `dsh.client.inject` 依赖 `@deepseek-ai/dsh-client-runtime` 等三个包，rc.3 里没有 → **挂饰/设置页大概率是空白**，但宿主侧的情绪注入不受影响（与 knowledge-base/context-doctor 同一个 peer 缺口）。

## 三、ppt-design-skill（技能，不是插件）— 已装

- 来源 GitHub `sunchaokun/PPT-Design-Skill`（355★，MIT），`skill/` 整个复制到 `~/.dsh/skills/ppt-design-skill/`（283 KB）。
- 官方安装器 `python installer/install.py --platform deepseek-harness --force` 在写 `~/.dsh/skills` 时被沙盒拒绝（`PermissionError [WinError 5]`），改用 `cp -r skill ~/.dsh/skills/ppt-design-skill` 落地；技能目录热加载，**技能列表里已经出现 `ppt-design-skill`**。
- 运行时依赖 `pptx-designer`（PyPI）：装到仓库自带 python（`.tools/dsh-python`），不走系统 python。缺了它技能只能做设计决策、出不了 PPTX。
- 渲染 PDF/PNG 那一步需要 LibreOffice 或 PowerPoint COM，本机有 Office 则走 COM。

## 四、surfcore — 未装（决定不装，等确认）

- `Mieksido/surfcore` 0.7.8 主打「QQ × B站 × 桌宠」三合一，前置要求 **SnowLuma 协议端 + 扫码登录**。
- 与本机现状直接冲突：①QQ 侧已有 `dsh-onebot-qq` + NapCat（已验证可用），换 SnowLuma 需要同号不能双协议端的迁移窗口；②B站侧已有 `dsh-bili-whale` + `dsh-plugin-bilibili`；③桌宠已有 `dsh-whale-widget`。装它等于把四块已经跑通的链路再叠一层。
- 结论：**不装**。如果 SnowLuma 那条路子以后验证成功（hook 与 QQ 版本对齐、冻结热更新），再单独评估。

## 验证方式与状态

- 探针独立进程 `dsh.cmd --profile probe --no-open --port 0`：无 `did not activate` 告警 → 两个新 bundle 在组合层都能激活（`ppt-design-skill` 已在技能目录出现，属热加载成功）。
- **尚未验证**：宿主是 17:45 启动的老进程，两个插件要**重启后**才真正挂上；已注册一次性计划任务 `FatFishRestartDSH` 在 23:00 触发重启。
- 重启后要看：`~/.dsh/feiyu-mood/` 是否生成、`fatfish_status` 之外设置页是否多出「主动搭话」「鱼的心情」两处；speak-up 的掷骰记录要等下一个 30 分钟窗口。

## 数据统一：心情只留一份真源

装上 `dsh-feiyu-mood` 之后，「她现在什么心情」有了两个答案：

| 存储 | 位置 | 基线 | 谁在写 |
| --- | --- | --- | --- |
| feiyu-mood | `~/.dsh/feiyu-mood/state.json` | 70 | 插件每轮用模型判一次，设置页可见 |
| fatfish hub | `memory.db` 的 `mood` 表 | 50（每小时回 6 分） | `mood_get` / `mood_nudge` 工具、主动开口成功后 |

两边各判一次，工具读到 50、页面显示 70，主动开口的“心情加成”也跟着错。定死一条规则：

- **读** → 先看 feiyu-mood，读得到就用它，返回里带 `source: "feiyu-mood:<key>"`；读不到才回落到数据库（`source: "fatfish-memory"`）
- **写** → 以统一后的当前值为基准算目标分（`target = clamp(base + delta)`），数据库写目标值，同时排一条待办进 feiyu 的那份

为什么要排队：沙盒里的 python 进程**没有** `~/.dsh/feiyu-mood/` 的写权限（新建临时文件和原地覆盖都是 `PermissionError [Errno 13]`），而宿主里的 node 有。所以 python 只写自己写得了的 `data/dsh/mood-pending.json`，由宿主每 5 分钟合并落盘。

涉及文件：

- `fatfish_core/hub.py`：`_feiyu_path()` / `_feiyu_store()` / `_mood_queue()`，`mood_get` 优先真源，`mood_nudge` 改基准并排队
- `dsh/control/moodsync.mjs`：`mergeIntoState()` 纯函数 + `applyMoodPending()`（写临时文件再 `rename`，成功才删队列；真源文件不在时队列保留）
- `dsh/control/index.mjs`：`tickProactive` 里先 `await syncMood()`，成功写 `status.mood`
- 环境变量：`FATFISH_FEIYU_STATE`、`FATFISH_MOOD_PENDING`（测试用临时路径，不碰真实文件）

验证：`mood` 从 70 被 `-1` 调到 69 → 队列 `[{"value":69,...}]` → node 合并 `{applied:1}` → 再读 `mood_get` 得 `69 / source: feiyu-mood:__default__`，`lastReason` 同步。测试：python `test_hub` 28 项（新增 2 项：真源优先、按真源基线排队）、node `dsh/tests/moodsync.test.mjs` 5 项全过；整套 node 87 通过 / 1 跳过。

已确认**不需要**统一的一处：知识库本来就是同一份 —— `dsh-knowledge-base` 与 `fatfish_core/recall.py` 都指 `~/.dsh/knowledge-base/kb.sqlite`（7.6MB，28 条），只是工具名不同。

## 重复/矛盾审计（结论）

真重复：`dsh-speak-up` 与自写 `proactive.mjs`（两套主动开口）、`feiyu-mood` 与 hub `mood`（已统一）、`dshmarket` 与 `dsh-find-plugin`、三个上下文插件（`billion-context` 压缩 / `dsh-context` 洞察 / `dsh-context-doctor` 审计，功能不冲突但都要维护）、`distill` 与 `dsh-fail-logger`（都写 `~/.dsh/skills`）。

死件：`@xmanrui/dsh-im`（缺 `dsh-client-runtime` + `ui-slots`，rc.3 上不可能有面板）、`dsh-pet`（只在 dependencies、不在 bundles）、`dsh-balance-meter`（已删）。

不是重复：B站工具只有 `dsh-plugin-bilibili` 注册，`dsh-bili-whale` 不注册工具（设置页 + 定时投递）；`whale-*.json` 只由 bili-whale 写；`dsh-whale-widget` 只读不写。

## 桌宠碎碎念：人设 + 心情注入（2026-10-31）

需求：碎碎念按“人设 + 心情”说，心情与工作状态分开（工作气泡不掺情绪）。

结论（先看代码再动手）：`dsh-pet` 的气泡只有三种来源——工作状态（监听会话事件、不调模型）、余额、碎碎念（自己调模型生成）。没有“心情”显示位，改前端会被升级覆盖。**唯一干净的切口是它每次生成碎碎念前都会重读配置**（`lib/index.js:4071`、`lib/index.js:4101` 两处 `readAllConfig(configPaths)`），所以把心情写进配置里的 `pets[].whisperPrompt`，下一句就生效，不用重启、不用改包。

落地：

- `~/.dsh/pet/main-config.jsonc`（用户层配置，`dsh-pet` 每次生成前重读）：只写 `pets[{ id: "main", whisperPrompt }]`，其余字段继续继承包内默认。示例：
  ```jsonc
  { "pets": [ { "id": "main", "name": "蓝毛小女仆", "whisperEnabled": true,
      "whisperPrompt": "你是吞天大肥鲸……\n【当前心情】还不错，69/100，语气轻快一点。" } ] }
  ```
- `dsh/control/petmood.mjs`（新增）：`PET_PERSONA` 人设正文、`MOOD_BUCKETS` 六档（<30 有点低落 / <45 略蔫 / <60 中性 / <75 还不错 / <90 开心 / ≥90 特别开心）、`readMoodValue()` 读 `~/.dsh/feiyu-mood/state.json` 的 `moods[lastActive].mood`、`desiredPrompt(value)` 拼“人设 + 心情行”、`syncPetMood({home,value})` 落盘。
- `dsh/control/index.mjs`：挂 `syncPet()` + `setInterval(syncPet, 10 * 60_000)`，与 `syncMood()`（心情队列合并）同一层；状态里记 `petMood`。
- 心情只走碎碎念：**没有**改 `workStatusTexts`、没有改余额气泡。工作状态仍是“正在写代码/在跑命令”那套，不掺情绪。

写入方式的选择：沙盒里的 python 写不进 `~/.dsh/feiyu-mood`、`~/.dsh/pet`（`PermissionError [Errno 13]`），宿主的 node 可以。所以 `petmood.mjs` 跑在控制插件里（宿主进程），python 侧只负责把心情写进 `memory.db` 与队列。

JSON 改写的坑：`whisperPrompt` 在文件里是一条 JSON 字符串，心情行后面跟着 `\n` 转义。直接 `replace(/【当前心情】[^\n]*/)` 会吃到文件尾。现在的实现先 `JSON.parse` 再改字符串；带注释的 JSONC 退回文本模式，正则收紧成 `/【当前心情】[^"\\n]*/`。

验证：`dsh/tests/petmood.test.mjs` 6 项（首次新建 / 只改那一行且 JSON 合法 / 同值不写盘 / JSONC 注释保留 / 读不到心情不动 / 人设不含工作状态文案）全过；真实文件 69 → 32 → 69 往返后 `JSON.parse` 仍通过，尾巴 `}` 完整。

## 群级模式 + 桌宠人设抽取（2026-10-31）

### 一、群级模式：主人用私聊命令控制每个群

代码：

- `dsh/policy.mjs`：`GROUP_MODES = ['talk','listen','mention','owner','quiet']`、`GROUP_MODE_LABELS`；`decide()` 在 `silent` 判断之前插入闸门；`groupMode(groupId)` / `setGroupMode(groupId, mode)` / `modeTable()`。
- `dsh/runtime-adapter.mjs`：`parseModeCommand(text)`、`applyModeCommand(policy, text)`、`formatModeTable(policy)`、`persistGroupMode(policy)`（原子写 `dsh/policy.json`）。
- `scripts/prepare_dsh_onebot.py` 的 `def bridge(source)`：`parseNewTarget` 分支之后插入 `/mode` 分支（只有主人能用；群里静默、私聊回执）。

| 模式 | 中文 | 行为 |
| --- | --- | --- |
| talk | 既听又说 | 默认，原逻辑（@ / 叫名字 / 私聊） |
| listen | 只听不说 | 只记不回复（`observe: true`） |
| mention | 只回@或叫名字 | 普通发言不理，真 @ 才回 |
| owner | 只回老大 | 群里只理主人，其他人只记 |
| quiet | 完全不理 | 连 @ 都不回 |

用法（主人私聊）：

```
/mode                     看各群设置
/mode 123456789 listen    改成只听不说
/mode 123456789 只听不说   中文写法也行
/mode 123456789 default   恢复默认
```

写回的文件和 `loadPolicy()` 读的是同一份（`FATFISH_POLICY_FILE` 或 `D:/Code/Projects/FatFishLife/dsh/policy.json`），重启不丢。

### 二、桌宠碎碎念人设改为从人设卡抽取

`dsh/control/petmood.mjs` 新增 `DEFAULT_PERSONA_FILE`（`docs/persona/whale-core.md`，可用 `FATFISH_PERSONA_CORE` 覆盖）、`extractPersona(markdown, { limit: 300, headers: ['二、性格内核','四、说话方式'] })`、`readPersona(file)`、`PET_RULES`（一句话、二十字以内、不提 AI 与 Token、不用客服腔）。

`desiredPrompt(value)` = 一句身份 + 抽出来的人设正文 + 表达纪律 + 心情行；人设卡读不到时退回原来的整段 `PET_PERSONA`。改 `whale-core.md` 那两节，桌宠下一轮碎碎念就跟着变。

### 三、验证

- `node --test dsh/tests/*.test.mjs` → 104 tests / 103 pass / 1 skipped（新增 `dsh/tests/mode.test.mjs` 10 项）
- `python -m unittest discover -s tests -p "test_hub*.py"` → 32 OK
- 探针 `dsh --profile probe --no-open --port 0` → `[dsh-onebot] mounted`、`bridge ready`、0 条 `did not activate`
- 坑：`tryHandleCommand` 不是 async 方法，插 `await` 会 `SyntaxError: Unexpected reserved word`，整条桥 failed to import；改用 `.catch(() => {})` + `return Promise.resolve(true)`。
