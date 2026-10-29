# AstrBot → DSH 切换运行手册

日期：2026-10-29。适用：生产 QQ 从 AstrBot 切到 DSH 桥（`dsh-onebot-qq` 适配版）。
前置状态：隔离验收 15 项已通过（见 [迁移对照表](DSH_FEATURE_MIGRATION-20261029.md)），生产 desktop 尚未安装桥。

本手册每一步都给「验证命令」和「失败怎么办」。**任何一步验证不通过就停下，不要继续下一步。**

## 0. 切换前现状（2026-10-29 17:45）

| 项 | 状态 |
| --- | --- |
| AstrBot WebUI 6185 | 在跑（HTTP 200） |
| AstrBot 的 aiocqhttp 适配器 | **启动失败**：`sock.bind` 报 `WinError 10013`，绑定 6199 失败，且不重试 |
| 结果 | **QQ 收发当前是断的**（NapCat 连不上 AstrBot） |
| 看门狗 | 今天已重启 AstrBot **62 次**，覆盖 09:46–17:36 |

也就是说：切换不是在打断一个健康服务，而是在接管一个已经断掉的服务。这一点降低了切换风险，但也意味着**拖得越久，机器人越久不回消息**。

## 1. 看门狗为什么在循环（判定方法，不是结论）

日志 `AstrBot/data/runtime_logs/watchdog.jsonl` 的实证分布：

| age_seconds | 次数 | 含义 |
| --- | --- | --- |
| 0 | 1 | 09:46 首次，找不到主进程（用户刚启动 NapCat） |
| 300–306 | 28 | 宽限期一过就被判不健康 |
| 583–617 | 25 | 撑过一轮 5 分钟，下一轮被杀 |
| 895–898 | 4 | 撑过两轮 |
| 21656 | 1 | 01:26 手动维护那次 |

脚本 [watchdog_astrbot.ps1:16-22](../../scripts/watchdog_astrbot.ps1) 的健康判据要求**两条同时成立**：

```powershell
$taskListener = @(Get-NetTCPConnection -LocalPort 6185 -State Listen)   # ① 必须看到监听
$taskHealthy  = $taskResponse.StatusCode -eq 200                        # ② 且 HTTP 200
```

而 AstrBot 自己的日志明确记录 `Starting WebUI at http://127.0.0.1:6185` 和 `WebUI is ready`，
本机实测 `http://127.0.0.1:6185/` 返回 200。所以 ② 通常成立。

**两个候选原因，需要用一条命令区分：**

- **假设 A：`Get-NetTCPConnection` 在这台机器上取不到真实监听表**（那么 ① 永远为假 → 必然每 5 分钟杀一次）
- **假设 B：AstrBot 确实周期性卡死**（事件循环被阻塞 → ② 失败）

判定命令（在**你自己的**普通 PowerShell 里跑，AstrBot 运行期间）：

```powershell
Get-NetTCPConnection -LocalPort 6185 -State Listen | Format-Table
(Invoke-WebRequest http://127.0.0.1:6185/ -UseBasicParsing).StatusCode
```

- 第一条**有输出**、第二条 200 → 探针正常，问题在 B（AstrBot 真的会卡），切换后再谈旧系统排障
- 第一条**空**、第二条 200 → 命中假设 A，看门狗在误杀健康进程

> 注：AstrBot 今天进入循环的时间点是 09:46，正好是 NapCat/QQ 被启动的时刻，但这个时间相关性**不足以**证明因果，不要据此下结论。

## 2. 切换前必须先做（否则会被旧服务抢回连接）

**必须先停掉看门狗**，否则它会在切换过程中把 AstrBot 重新拉起，而 AstrBot 会重新绑定 6199 抢 NapCat：

```powershell
Stop-ScheduledTask -TaskName "FatFishLife-Watchdog"
Disable-ScheduledTask -TaskName "FatFishLife-Watchdog"
```

验证：`Get-ScheduledTask -TaskName "FatFishLife-Watchdog"` 的 `State` 应为 `Disabled`。

备份 profile（安装器本身也会备份，这里是额外一层）：

```powershell
Copy-Item "$env:USERPROFILE\.dsh\profiles\desktop" "$env:USERPROFILE\.dsh\profiles\desktop.bak-$(Get-Date -Format yyyyMMdd-HHmmss)" -Recurse
```

## 3. 安装桥（DSH 必须完全退出）

关闭 DSH 窗口**并且退出托盘**，然后：

```powershell
cd D:\Code\Projects\FatFishLife
powershell -ExecutionPolicy Bypass -File scripts\dsh_install_plugins.ps1 -IncludeQqBridge
```

预期：脚本先备份，再装 `dsh-fatfish-life` 控制包与 OneBot 桥，不改 NapCat 配置。

失败怎么办：脚本会打印原因并退出；把输出保留下来。**不要**用 `-SkipQqBridge` 假装成功。

## 4. 重开 DSH 并验证桥已加载

重开 DSH 后：

```powershell
cd D:\Code\Projects\FatFishLife
.\.tools\dsh-python\Scripts\python.exe -X utf8 scripts\dsh_selfcheck.py --json
```

看 `QQ 桥` 这一项：已安装则不再报 `未安装`。它仍可能报「未连接」——这是正常的，
因为 NapCat 此时还指着 AstrBot。

## 5. 把 NapCat 指向 DSH

改 NapCat 的 OneBot 反向 WS 目标端口，从 AstrBot 的 **6199** 指向 DSH 桥监听的端口
（桥的实际端口见安装后的 profile 配置，不要凭记忆填）。

改之前先确认没人占着旧端口：

```powershell
netstat -ano | findstr :6199
```

切换顺序：**先启动 DSH 桥，再改 NapCat**，避免中间出现两端都没接的空窗过长。

验证：NapCat 控制台出现反向 WS 连接成功；DSH 侧桥日志出现连接事件。

## 6. 停用 AstrBot（切换验证通过之后，不要提前）

至少满足：桥已加载、NapCat 已连上、一条真实消息能得到真实回复。

```powershell
# 1) 停 AstrBot 主进程
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'main\.py' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# 2) 确认端口释放
netstat -ano | findstr :6199
```

**保留冷备份**：不要删除 `D:\Code\Apps\AstrBot`，不要卸载插件目录。
按主方案，AstrBot 目录最终只作为冷备份存在。

## 7. 回滚

任何一步不通，按顺序回退：

1. 改回 NapCat 的目标端口为 6199
2. 恢复看门狗：`Enable-ScheduledTask -TaskName "FatFishLife-Watchdog"`
3. 用脚本 `FatFishLife-Start` 计划任务拉起 AstrBot
4. 若 DSH 侧装坏了：用第 2 步的 `desktop.bak-*` 还原 profile 后重开 DSH

回滚**只回退配置与进程**，不要用旧库整库覆盖——切换期间产生的新消息要保留。

## 8. 现在还不能算完成的项

- 媒体出口（最终回复 → 语音/图片 → OneBot 发送）尚未挂进生产，属 P-B
- 运营执行器（推荐、主动消息、风格学习、日记动态）尚未迁完，属 P-C
- 真实账号效果（口吻、延迟、媒体实际播放）只有真人对话能验收

在这些完成前，桥能收发文字，但不能宣称「功能已全部迁移」。
