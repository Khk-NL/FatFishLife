# 双 bot 环境搭建

记录本机已经验证过的安装方式。换机时按顺序做。

## 目录

```
D:\Code\Apps\
├── AstrBot\          AstrBot v4.29.1 源码 + .venv (Python 3.12)
├── NapCat\           NapCat.Shell，注入 D:\Q\QQ.exe
├── bili-venv\        bili-agent 0.6.0 独立环境
├── bili-data\        B 站二维码与临时文件
└── gh-bin\           GitHub CLI 便携版（推送用）
```

项目内的 `bots/` 是插件源码，通过 junction 挂到 AstrBot：

```
D:\Code\Apps\AstrBot\data\plugins\astrbot_plugin_fatfish_memory
D:\Code\Apps\AstrBot\data\plugins\astrbot_plugin_fatfish_bili
```

先在 AstrBot 使用的 Python 环境安装项目，提供统一数据层 `fatfish_core`：

```powershell
D:/Code/Apps/AstrBot/.venv/Scripts/python.exe -m pip install -e D:/Code/Projects/FatFishLife
```

部署的自研入口为 memory、bili、offline、lore；表情交给社区 `meme_manager`，主动消息使用 `proactive_chat`。旧自研 stickers 源码已移除，历史素材及运行数据不删除。`fatfish_life` 当前没有完整插件入口，不挂载。服务器步骤见 [部署说明](../deploy/README.md)，其中社区插件目录保持可写，不会被自研源码覆盖。

## AstrBot

```powershell
cd D:\Code\Apps
git clone --depth 1 https://github.com/AstrBotDevs/AstrBot.git
cd AstrBot
C:\Users\kongb\AppData\Local\Programs\Python\Python312\python.exe -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

首次启动会下载 WebUI 到 `data/dist`，并生成随机初始密码，打印在日志里。默认端口 `6185`，OneBot v11 反向 WS 端口 `6199`。

`data/cmd_config.json` 里已写入：

```json
"platform": [
  {"id": "napcat", "type": "aiocqhttp", "enable": true,
   "ws_reverse_host": "0.0.0.0", "ws_reverse_port": 6199, "ws_reverse_token": ""}
]
```

`dashboard.host` 设为 `127.0.0.1`，不对外暴露。

## NapCat

下载 `NapCat.Shell.zip` 解压到 `D:\Code\Apps\NapCat`，直接启动：

```powershell
$env:NAPCAT_PATCH_PACKAGE = "D:\Code\Apps\NapCat\qqnt.json"
$env:NAPCAT_LOAD_PATH = "D:\Code\Apps\NapCat\loadNapCat.js"
$env:NAPCAT_INJECT_PATH = "D:\Code\Apps\NapCat\NapCatWinBootHook.dll"
$env:NAPCAT_LAUNCHER_PATH = "D:\Code\Apps\NapCat\NapCatWinBootMain.exe"
$env:NAPCAT_MAIN_PATH = "D:\Code\Apps\NapCat\napcat.mjs"
cd D:\Code\Apps\NapCat
.\NapCatWinBootMain.exe "D:\Q\QQ.exe" "D:\Code\Apps\NapCat\NapCatWinBootHook.dll"
```

二维码出现在控制台，同时保存到 `cache\qrcode.png`。WebUI 在 `6099`。

**必须先退出已登录的 QQ**，否则 NapCat 会接管主号。只给小号用。

## bili-cli

```powershell
C:\Users\kongb\AppData\Local\Programs\Python\Python312\python.exe -m venv D:\Code\Apps\bili-venv
D:\Code\Apps\bili-venv\Scripts\pip.exe install bili-agent
D:\Code\Apps\bili-venv\Scripts\bili.exe auth login --qr-out D:\Code\Apps\bili-data\qr.png
```

二维码 180 秒有效。扫码后：

```powershell
D:\Code\Apps\bili-venv\Scripts\bili.exe auth status --wait 120
```

凭据默认在 `%APPDATA%\bili-cli\`；插件通过 `BILI_CLI_HOME` 指定独立目录，避免和手工使用冲突。

## 启动

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_bots.ps1
```

脚本在启动 AstrBot 前设置 `PYTHONIOENCODING=utf-8`，避免 Windows 把重定向日志按默认代码页编码而报 `UnicodeEncodeError`。单独启动或重定向日志时，也应先在同一 PowerShell 中设置 `$env:PYTHONIOENCODING = "utf-8"`。

## 配置

AstrBot WebUI → 插件 → `astrbot_plugin_fatfish_memory`：

- `owner_ids`：`qq:<主人QQ>,bilibili:<主人UID>`；填写主人的身份，不是 bot 小号
- `record_all_messages`：默认开
- `retention_days`：默认 90；每天首次成功记录消息时清理过期事件，0 或负数关闭。总结和札记表不清理；失败保留当日重试机会

`astrbot_plugin_fatfish_bili`：

- `bili_exe`：`D:/Code/Apps/bili-venv/Scripts/bili.exe`
- `owner_uid`：你的 B 站 UID
- `dry_run_writes`：默认 true，先看预览
- `enable_inbox_poll`：默认关，开了会消耗 B 站未读状态

自动读取收件箱或发送回复时，遇到未登录、登录过期、风控或验证码错误，会暂停本进程的自动回复，只通知一次。暂停后不再拉取消息、生成回复或自动发送；`/bili 处理` 也不会绕过暂停，`/bili 状态` 会显示原因。普通手动查询和写操作仍按原权限执行。

在 B 站完成登录、风控或验证码处理后，由主人或管理员在私聊中发送 `/bili 恢复`。该命令只检查登录状态，确认已登录后解除暂停，不立即拉取或发送消息；检查失败或尚未登录时保留原暂停原因。单独 `/bili 确认` 不解除暂停。暂停状态仅保存在当前进程，重启插件后清除。

### 每日啊噗噜派

AstrBot WebUI → 插件 → `astrbot_plugin_fatfish_offline`：

- `daily_apple_pie_group_id`：自行填写要接收口令的 QQ 群号；默认留空，不会发送。清空可停用。
- `daily_apple_pie_platform_id`：默认 `napcat`，对应 AstrBot 中 QQ 连接的 ID。

保存后重载插件生效。每天按北京时间在 18:01、19:01、20:01 分别按 25%、50%、75% 抽签；此前未中签时，21:01 起概率为 100%。每小时只抽一次，周末照常，不受上班离线时段限制，不调用模型，只发固定的“啊噗噜派！”。

当天最多尝试发送一次，记录保存在统一 SQLite 的运行状态中；旧 `state.json` 仅首次导入并保留。重载、重启或换群都不重置当天结果。服务错过时间后只抽当前时段，不追补之前的轮次；平台未就绪时不消耗抽签。发送前先保存当天记录，发送异常、结果未确认或中途取消后不自动重发，避免重复。

## 故障排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `/bili 登录` 说 login_expired | 二维码 3 分钟过期 | 重新 `/bili 登录` |
| 自动回复显示已暂停 | 轮询或自动发送遇到鉴权、风控或验证码错误 | 先在 B 站解决问题，再在主人私聊发送 `/bili 恢复`；该命令不会立即回复消息 |
| NapCat 二维码失效 | 自动刷新，旧图作废 | 看最新 `cache\qrcode.png` |
| OneBot 未连接 | NapCat 没登录或 token 不一致 | 看 AstrBot 日志 `aiocqhttp` |
| push 卡住 | GitHub 凭据未配置 | `gh auth login`，再 `gh auth setup-git` |
| 插件改动不生效 | AstrBot 只在启动时加载 | 重启 AstrBot，WebUI 里重载插件 |
