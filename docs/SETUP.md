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

## 故障排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `/bili 登录` 说 login_expired | 二维码 3 分钟过期 | 重新 `/bili 登录` |
| NapCat 二维码失效 | 自动刷新，旧图作废 | 看最新 `cache\qrcode.png` |
| OneBot 未连接 | NapCat 没登录或 token 不一致 | 看 AstrBot 日志 `aiocqhttp` |
| push 卡住 | GitHub 凭据未配置 | `gh auth login`，再 `gh auth setup-git` |
| 插件改动不生效 | AstrBot 只在启动时加载 | 重启 AstrBot，WebUI 里重载插件 |
