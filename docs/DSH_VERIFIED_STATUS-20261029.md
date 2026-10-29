# DSH 迁移验证状态（可复现）

更新：2026-10-29 19:10。本文件回答一个问题：**哪些东西真的迁过来了，证据是什么，怎么自己复现。**
不写「已迁移一部分」这种无法核对的话。

## 证据分级（每项功能必须落到一格）

| 级别 | 含义 | 能说明什么 |
| --- | --- | --- |
| ① 源码通过 | 代码在仓库里，单元/回归测试绿 | 逻辑对，不代表能跑 |
| ② 隔离验证 | 一次性 DSH profile + mock 模型 + 假 OneBot | 宿主能加载、策略生效；**不含真实账号** |
| ③ 生产加载 | 装进日常 desktop，宿主进程实际加载 | 部署可行；**不含真实对话** |
| ④ 真实账号 | 真 QQ 收发、真模型口吻、真语音播放 | 唯一能说「能用」的证据 |

## 当前状态总表

| 能力 | 实现位置 | 等级 | 证据 / 复现命令 |
| --- | --- | --- | --- |
| 记忆库 | `dsh/service/fatfish_memory_mcp.py` | ③ | `python scripts/dsh_selfcheck.py` → `memory.db events 4845 / 候选197 / 已确认12`；MCP 实枚举 25 工具 |
| 图库 | `fatfish_core/gallery.py` 经 MCP | ③ | 同上 → `图库 164 张，损坏 0` |
| 知识库 | `dsh-knowledge-base` 0.1.5 | ③ | 同上 → `DSH 知识库 28 条记录` |
| 私人笔记 | `dsh-obsidian` 0.2.6 | ③ | profile bundles 含该包；写入权限未验收 |
| 人格 preset | `dsh/preset-apple-le.yml` | ① | 与 `docs/persona/apple-le-core.md` 逐字一致（P2.9 断言） |
| 回复策略/静默/工作窗口 | `dsh/policy.mjs` | ② | `node --test dsh/tests/*.test.mjs` → 43 项 |
| B 站只读 | `dsh-plugin-bilibili` 0.2.4 | ③ | 自检 → `exe=bili.exe，写操作=关` |
| 本地模型兜底 | `fatfish_core/local_llm.py` | ② | 自检 WARN：端口可连，**未推理** |
| TTS | `fatfish_core/tts.py` 经 MCP | ② | 自检 WARN：**未合成过一次真语音** |
| 媒体出口 | 决策在 `delivery.py`，发送未接线 | ① | 见 [媒体出口方案](DSH_MEDIA_OUTLET-20261029.md) |
| 定时/主动 | 只有 `dsh/rules.md` 文档 | ① | **执行器未注册** |
| QQ 通道 | `prepared-onebot`（上游 0.9.6 适配） | ③ | 见下节：**已在真实宿主进程挂载并监听 8643** |
| Skill | 未迁移 | — | 无 |

复现全套：

```powershell
cd D:\Code\Projects\FatFishLife
node --test dsh/tests/*.test.mjs                                              # 43 项
.\.tools\dsh-python\Scripts\python.exe -X utf8 -m unittest discover -s tests -p "test_dsh_*.py"   # 39 项
.\.tools\dsh-python\Scripts\python.exe -X utf8 scripts\dsh_selfcheck.py      # 10 项生产状态
.\.tools\dsh-python\Scripts\python.exe -X utf8 scripts\dsh_bridge_check.py   # 桥是否真的就绪
```

隔离验收要额外指定工作区内的 pnpm store（受限沙箱下工作区外 SQLite 取不到锁）：

```powershell
$env:FATFISH_SMOKE_STORE = "D:/Code/Projects/FatFishLife/outputs/dsh-migration/native-smoke/.pnpm-store"
.\.tools\dsh-python\Scripts\python.exe -X utf8 scripts\dsh_native_smoke.py
```

## 2026-10-29 19:10：桥在真实宿主进程里挂载成功（关键进展）

把 profile 复制到工作区、换名 `probe`、用独立 `DSH_HOME` 起**第二个真实宿主进程**（非 mock、非一次性 smoke），
直接验证手动安装路径能不能用。结果：

```
[dsh-onebot] mounted (mode=reverse, media=...)
[dsh-onebot] reverse WS server listening on ws://127.0.0.1:8643 (path /ws or /)
[dsh-onebot] bridge ready (0 resumed chat(s))
```

`8643` 实测 OPEN。`dsh --profile probe --dump-config` 也显示组合树里 `dsh-onebot` 条目带着完整 config，
且桥自带的 `onebot-settings-remote` 一并挂上。

**途中发现一个硬门槛**：首次启动报
`Error: reverse mode requires a non-empty accessToken`，行为是 `dsh: warning: 1 entry did not activate`、
桥不监听。补上 `accessToken` 后立刻正常。这个前提之前没人记录，安装器与手册已同步修正——
token 必须与 NapCat 的 `token` 字段**完全一致**。

尚未做：真实 QQ 往返。探针用的是独立 home，没有把 NapCat 指过去验证收发。

## 2026-10-29 19:17：生产宿主已挂载桥并监听 8643（无需重启）

`Get-NetTCPConnection -LocalPort 8643 -State Listen` 的占用者是 **PID 13568**，即生产 DSH 宿主本身，
不是残留进程。也就是说改完 `cordis.patch.yml` 后，desktop profile **热重载**并挂载了桥。

`scripts/dsh_bridge_check.py` 现在 **`ok: true`**：依赖、bundles、顶层 patch 段、botQQ、端口一致、
端口可连 六项全部 PASS。唯一 WARN 是「尚无 qq-trace.jsonl」——因为桥还没接待过客户端。

**真正卡住的地方不是 DSH，是 QQ 客户端没在跑**：`QQ.exe` 进程数 0，只剩一个 5MB 的
`NapCatWinBootMain`。19:02 那次 QQ 崩溃之后就没起来过，所以没有任何 OneBot 客户端能连上 8643。
启动 QQ/NapCat 需要管理员权限（launcher.bat 的 QQ 注入），不是这里能自动完成的。

## 已知未验证项（不要当成已完成）

1. **真实 QQ 往返一次都没有过**。隔离验收用假 OneBot 与 mock 模型，宿主挂载验证也没接真实 NapCat。
2. **真实模型口吻未验收**。人设文本进过请求（②有断言），但真模型说什么没人看过。
3. **语音合成与播放未验收**。`allowSynthesis` 默认关，一次都没真合成。
4. **运营执行器未注册**。推荐、主动消息、风格学习、日记动态都还只有文档与决策函数。
5. **媒体最终投递未接线**。见媒体出口方案，等选型。
6. **Skill 未迁移**。

## 一个容易误判的坑

`~/.dsh/profiles/node_modules/@deepseek-ai/*` 下 253 个包**全部是断掉的 Junction**，
指向已不存在的 `D:\Code\dsh\deepseek-harness\apps\cli\node_modules\...`。

这**不能**用来断定插件挂不上：宿主导入插件走的是 Electron/asar 上下文，隔离验收里桥确实挂载成功过。
用普通 `node -e "import(...)"` 去测会得到 `MODULE_NOT_FOUND`，那个结果不代表宿主行为。
判断挂载只有一条路：看宿主日志里的 `[dsh-onebot] mounted`。

同理，`scripts/dsh_selfcheck.py` 原来在「包在但未监听」时写「peer 依赖阻塞」，那是没观测就下的结论，已改掉。
