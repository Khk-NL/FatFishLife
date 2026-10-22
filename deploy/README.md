# 服务器部署准备

这份配置把 AstrBot、NapCat、B 站执行层和本地视频工具放入同一套目录。默认关闭 B 站自动回复、轮询和真实写操作。它不会迁移本机账号、凭据或私人记忆。

## 已核对的基础

- [AstrBot 官方 Docker 文档](https://github.com/AstrBotDevs/astrbot-docs/blob/v4/zh/deploy/astrbot/docker.md) 与 [v4.29.1 Dockerfile](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.1/Dockerfile)：工作目录 `/AstrBot`，持久目录 `/AstrBot/data`，基础镜像包含 FFmpeg、libass 和 Noto CJK 字体。
- [NapCat-Docker 官方说明](https://github.com/NapNeko/NapCat-Docker)：QQ 与配置持久目录、`reverse_ws`、`ONEBOT_URL` 及 WebUI token 初始化方式。
- [AstrBot 的 NapCat 接入说明](https://github.com/AstrBotDevs/astrbot-docs/blob/v4/zh/platform/aiocqhttp/napcat.md)：同网络使用 `ws://astrbot:6199/ws`。
- 2026-10-23 从 Docker Hub 查询并固定了 AstrBot v4.29.1 与 NapCat 镜像摘要。后续升级应重新核对摘要和本项目回归结果。

`Dockerfile` 沿用 AstrBot 基础镜像，在独立环境 `/opt/bili-venv` 安装 bili-agent 0.6.0，避免改动 AstrBot 的依赖集合；项目用可编辑安装保留素材相对路径。`Dockerfile.dockerignore` 只允许项目代码和构建配置进入构建上下文，不打包本机 `.env`、数据库、输出和账号数据。

## 先检查，再准备目录

服务器需有 Docker Engine 与 Compose 插件。先在仓库根目录执行：

```bash
python deploy/prepare.py
python deploy/prepare.py --write
```

第一个命令只检查文件；第二个只创建 `deploy/state/` 和缺失的插件初始配置，已有配置保持不变。`--state-dir` 可检查或准备其他位置；使用该选项部署时，也要同步修改 Compose 中所有 `./state` 挂载路径。

将 `deploy/.env.example` 复制为 `deploy/.env`，在本机填写新的 `NAPCAT_WEBUI_TOKEN`，按服务器用户填写 UID/GID。状态目录应允许该 UID/GID 读写。不要把 `.env` 或 `state/` 提交到仓库。

检查渲染后的配置并构建：

```bash
docker compose -f deploy/compose.yaml config --quiet
docker compose -f deploy/compose.yaml build
```

本轮 Windows 环境没有 Docker，因此只完成了 Python 预检、模板校验和 Compose 的静态解析；镜像构建、Linux 运行及账号接入仍需在目标服务器验证。

## 账号持有人确认后启动

```bash
docker compose -f deploy/compose.yaml up -d
```

WebUI 仅绑定服务器本机：AstrBot `127.0.0.1:6185`，NapCat `127.0.0.1:6099`。远程访问用 SSH 端口转发；OneBot 6199 只在容器网络内开放。

首次启动后：

1. 在 AstrBot 初始化管理员、模型和实际使用的人设；默认配置没有模型密钥。
2. 添加 `aiocqhttp` 适配器，监听 `0.0.0.0:6199`。在 NapCat 核对反向 WebSocket 地址、消息格式 Array 和双方 token。
3. 用独立 QQ 小号完成登录，确认 AstrBot 日志出现 OneBot 连接成功；不要直接复制本机 QQ 会话。
4. 填写记忆插件的 `owner_ids`、B 站插件的 `owner_uid` 和 `owner_qq`。B 站凭据留在容器持久目录，通过 `/bili 登录`、`/bili 确认` 登录。
5. 检查人设库的 Linux 路径 `/opt/fatfish/docs/persona/apple-le-full.md`。五个插件整个目录一同挂载，确保相邻插件的共享模块可以导入。
6. 先在主人私聊验证公开/私人记忆隔离、离线时段、角色设定、表情和 B 站预览。确认后再单独开启轮询和真实写操作。

## 媒体与运行验收

```bash
docker compose -f deploy/compose.yaml exec astrbot python -m fatfish_video doctor
docker compose -f deploy/compose.yaml exec astrbot /opt/bili-venv/bin/bili --help
docker compose -f deploy/compose.yaml exec astrbot python -m fatfish_video render /opt/fatfish/examples/single.json --output /opt/fatfish/outputs/server-single.mp4
```

输出保存在 `deploy/state/outputs/`。确认中文字体、声音和画面后再用于正式内容。AstrBot 的进程重启由 Compose 处理；账号风控、验证码或登录失效需要本人处理，不由重启循环解决。

日常保留 `state/astrbot`、`state/napcat`、`state/qq` 和所需成片。复制 SQLite 前停止相关服务，或使用 SQLite 的备份接口；不要只拷贝正在使用的单个 `.db` 文件而忽略 WAL。部署配置未自动清理成片，磁盘保留天数由你在服务器验收时确定。
