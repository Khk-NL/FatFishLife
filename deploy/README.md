# 服务器部署准备

这份配置默认运行 AstrBot、NapCat 两个服务，B 站 CLI 与视频工具按需执行。默认关闭 B 站自动回复、轮询、真实写操作和本地模型，不下载 Qwen。源码包不含本机账号、凭据或私人记忆。

## 已核对的基础

- [AstrBot 官方 Docker 文档](https://github.com/AstrBotDevs/astrbot-docs/blob/v4/zh/deploy/astrbot/docker.md) 与 [v4.29.1 Dockerfile](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.1/Dockerfile)：工作目录 `/AstrBot`，持久目录 `/AstrBot/data`，基础镜像包含 FFmpeg、libass 和 Noto CJK 字体。
- [NapCat-Docker 官方说明](https://github.com/NapNeko/NapCat-Docker)：QQ 与配置持久目录、`reverse_ws`、`ONEBOT_URL` 及 WebUI token 初始化方式。
- [AstrBot 的 NapCat 接入说明](https://github.com/AstrBotDevs/astrbot-docs/blob/v4/zh/platform/aiocqhttp/napcat.md)：同网络使用 `ws://astrbot:6199/ws`。
- 2026-10-23 从 Docker Hub 查询并固定了 AstrBot v4.29.1 与 NapCat 镜像摘要。后续升级应重新核对摘要和本项目回归结果。

`Dockerfile` 沿用 AstrBot 基础镜像，在独立环境 `/opt/bili-venv` 安装 bili-agent 0.6.0；项目可编辑安装包含 `fatfish_core`、视频、故事和投稿工具，并在构建时检查共享数据接口能否导入。构建上下文仅允许这些代码和 `pyproject.toml`，素材从服务器目录只读挂载。

四个自研插件逐个挂载：memory、bili、offline、lore。没有覆盖 `/AstrBot/data/plugins` 整个目录，社区 `meme_manager`、`proactive_chat` 可继续安装和更新在持久数据目录中。自研 stickers 已由 `meme_manager` 替代，其源码不再部署；历史图片、索引和运行数据保留。`fatfish_life` 目前只有独立辅助函数，没有插件入口，不作为完整插件部署。lore 暂留，待原生知识库实际检索验收后再停用。

## 先检查，再准备目录

服务器需有 Docker Engine 与 Compose 插件。先在仓库根目录执行：

```bash
python deploy/prepare.py
python deploy/prepare.py --write
python deploy/prepare.py --bundle outputs/fatfishlife-server-code.zip
```

第一个命令只检查文件；第二个只创建 `deploy/state/` 和缺失的四份插件初始配置，已有配置及社区插件保持不变。第三个打包构建文件、四个插件、共享代码、素材、样例和人设文档，并附文件 SHA-256 清单；不包含 `.env`、数据库、日志、运行状态和社区插件。目标 ZIP 已存在时拒绝覆盖。解压后可在服务器按本文操作。

`--state-dir` 可检查或准备其他位置；使用该选项部署时，也要同步修改 Compose 中所有 `./state` 挂载路径。源码包不自动迁移 `meme_manager` 的图片与索引，完整表情库应随其插件数据目录单独备份和恢复。

将 `deploy/.env.example` 复制为 `deploy/.env`，在本机填写新的 `NAPCAT_WEBUI_TOKEN`，按服务器用户填写 UID/GID。状态目录应允许该 UID/GID 读写。不要把 `.env` 或 `state/` 提交到仓库。

检查渲染后的配置并构建：

```bash
docker compose -f deploy/compose.yaml config --quiet
docker compose -f deploy/compose.yaml build
```

本轮 Windows 环境没有 Docker，仅完成 Python 预检、迁移包内容检查和 Compose 静态解析；镜像构建、Linux 运行及账号接入需在目标服务器验证。

当前目标服务器只有约 2.5 GB 内存，可用内存约 44 MB，不能据此启动或构建新服务。部署前应先释放或增加内存并核实实际余量；默认配置已关闭本地 Qwen，以免与 AstrBot、NapCat 争抢内存。需要兜底时，可把插件的 `local_model_url` 改为可达的 PC Ollama 地址，再开启 `local_model_enabled`；容器内的 `127.0.0.1` 不指向本机 PC。连接可用性、休眠恢复和模型请求需另行验收，不新增 Ollama 常驻容器。

## 启动与接入

```bash
docker compose -f deploy/compose.yaml up -d
```

WebUI 仅绑定服务器本机：AstrBot `127.0.0.1:6185`，NapCat `127.0.0.1:6099`。远程访问用 SSH 端口转发；OneBot 6199 只在容器网络内开放。

首次启动后：

1. 在 AstrBot 初始化管理员、模型和实际使用的人设；默认配置没有模型密钥。
2. 添加 `aiocqhttp` 适配器，监听 `0.0.0.0:6199`。在 NapCat 核对反向 WebSocket 地址、消息格式 Array 和双方 token。
3. 用独立 QQ 小号完成登录，确认 AstrBot 日志出现 OneBot 连接成功；不要直接复制本机 QQ 会话。
4. 填写记忆插件的 `owner_ids`、B 站插件的 `owner_uid` 和 `owner_qq`。B 站凭据留在容器持久目录，通过 `/bili 登录`、`/bili 确认` 登录。
5. 检查人设库 Linux 路径 `/opt/fatfish/docs/persona/apple-le-full.md`；确认四个自研插件正常加载。共享数据包已安装到 Python 环境，不依赖相邻插件导入。
6. 在 AstrBot 插件市场安装 `meme_manager` 和所需的 `proactive_chat`，或恢复已备份的源码与数据。主动消息仅在配置了目标会话后启用。
7. 在主人私聊验证公开／私人记忆隔离、离线时段、角色设定、表情和 B 站预览，再按实际需要开启轮询及真实写操作。

## 媒体与运行验收

```bash
docker compose -f deploy/compose.yaml exec astrbot python -m fatfish_video doctor
docker compose -f deploy/compose.yaml exec astrbot /opt/bili-venv/bin/bili --help
docker compose -f deploy/compose.yaml exec astrbot python -m fatfish_video render /opt/fatfish/examples/single.json --output /opt/fatfish/outputs/server-single.mp4
```

输出保存在 `deploy/state/outputs/`。确认中文字体、声音和画面后再用于正式内容。AstrBot 的进程重启由 Compose 处理；账号风控、验证码或登录失效需要本人处理，不由重启循环解决。

日常保留 `state/astrbot`、`state/napcat`、`state/qq` 和所需成片。复制 SQLite 前停止相关服务，或使用 SQLite 的备份接口；不要只拷贝正在使用的单个 `.db` 文件而忽略 WAL。部署配置未自动清理成片，磁盘保留天数由你在服务器验收时确定。
