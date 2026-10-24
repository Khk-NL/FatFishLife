# 服务器部署准备

这份配置默认运行 AstrBot、NapCat 两个服务，B 站 CLI 与视频工具按需执行。默认关闭 B 站自动回复、轮询、生活动态发布、Obsidian 同步和本地模型，不下载 Qwen。视频投稿需要主人看片并明确确认，初始分区留空。源码包不含本机账号、凭据或私人记忆。

## 已核对的基础

- [AstrBot 官方 Docker 文档](https://github.com/AstrBotDevs/astrbot-docs/blob/v4/zh/deploy/astrbot/docker.md) 与 [v4.29.1 Dockerfile](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.1/Dockerfile)：工作目录 `/AstrBot`，持久目录 `/AstrBot/data`，基础镜像包含 FFmpeg、libass 和 Noto CJK 字体。
- [NapCat-Docker 官方说明](https://github.com/NapNeko/NapCat-Docker)：QQ 与配置持久目录、`reverse_ws`、`ONEBOT_URL` 及 WebUI token 初始化方式。
- [AstrBot 的 NapCat 接入说明](https://github.com/AstrBotDevs/astrbot-docs/blob/v4/zh/platform/aiocqhttp/napcat.md)：同网络使用 `ws://astrbot:6199/ws`。
- 2026-10-23 从 Docker Hub 查询并固定了 AstrBot v4.29.1 与 NapCat 镜像摘要。后续升级应重新核对摘要和本项目回归结果。

`Dockerfile` 沿用 AstrBot 基础镜像，在独立环境 `/opt/bili-venv` 安装 bili-agent 0.6.0；项目可编辑安装包含 `fatfish_core`、视频、故事和投稿工具，并在构建时检查共享数据接口能否导入。构建上下文仅允许这些代码和 `pyproject.toml`，素材从服务器目录只读挂载。

九个自研插件逐个只读挂载：memory、bili、offline、lore、life、story、obsidian、steam、voice。没有覆盖 `/AstrBot/data/plugins` 整个目录，社区 `meme_manager`、`proactive_chat` 可继续安装和更新在持久数据目录中。自研 stickers 已由 `meme_manager` 替代，其源码不再部署；历史图片、索引和运行数据保留。lore 暂留，待原生知识库实际检索验收后再停用。

新增能力的准备状态如下：

| 插件 | 初始配置 | 接入后仍需验证 |
| --- | --- | --- |
| life | 私人每日总结开启，公开动态发布关闭，空间账号留空 | 主人身份、日记权限、双平台发布回执 |
| story | 主人、标签留空，`zone`、`tid` 为 0；可制作看片，不能投稿 | 主人 QQ 收到封面与成片，确认编号后提交审核 |
| obsidian | 同步关闭，vault、主人和向量模型留空，使用独立私人知识库名称 | 主人给出 vault 后，只读挂载并验证私聊检索 |
| steam | `cn` 区域，只读按需查询，代理留空，无需 Web API Key | 商店连接；遇到 403 时配置容器可达代理后实测 |
| voice | 仅注册原生 TTS 类型，provider 模板为禁用状态，不创建或修改已配置 provider | 填入密钥和声线后显式选择；默认 CosyVoice2、speed=1.1，需本人听验 |

这些能力通过共享成长记录保留实际成功、失败或待核验结果，不把“配置存在”当作使用成功，也不把私人笔记和审阅内容复制到公开素材。

## 先检查，再准备目录

服务器需有 Docker Engine 与 Compose 插件。先在仓库根目录执行：

```bash
python deploy/prepare.py
python deploy/prepare.py --write
python deploy/prepare.py --bundle outputs/fatfishlife-server-code.zip
```

第一个命令只检查文件；第二个只创建 `deploy/state/` 和缺失的八份插件初始配置，已有配置及社区插件保持不变。voice 没有独立插件配置，只注册默认禁用的原生 provider 模板，需本人在 AstrBot 中填写并启用。第三个打包构建文件、九个插件、共享代码、素材、样例和人设文档，并附文件 SHA-256 清单；不包含 `.env`、数据库、日志、运行状态和社区插件。目标 ZIP 已存在时拒绝覆盖。解压后可在服务器按本文操作。

`--state-dir` 可检查或准备其他位置；使用该选项部署时，也要同步修改 Compose 中所有 `./state` 挂载路径。源码包不自动迁移 `meme_manager` 的图片与索引，完整表情库应随其插件数据目录单独备份和恢复。

将 `deploy/.env.example` 复制为 `deploy/.env`，在本机填写新的 `NAPCAT_WEBUI_TOKEN`，按服务器用户填写 UID/GID。状态目录应允许该 UID/GID 读写。不要把 `.env` 或 `state/` 提交到仓库。

检查渲染后的配置并构建：

```bash
docker compose -f deploy/compose.yaml config --quiet
docker compose -f deploy/compose.yaml build
```

本轮仅验证 Python 预检、配置保留、源码包内容和 Compose 静态结构；未构建镜像、拉取镜像或启动 Docker 服务。此前的 Windows 检查没有 Docker，目标服务器的镜像构建、Linux 运行和账号接入仍需实测。

此前记录的目标服务器内存约 2.5 GB、可用约 44 MB，本轮未重新读取服务器状态。部署前应核实实际余量，必要时先释放或增加内存；默认配置已关闭本地 Qwen。需要兜底时，可把插件的 `local_model_url` 改为可达的 PC Ollama 地址，再开启 `local_model_enabled`；容器内的 `127.0.0.1` 不指向本机 PC。连接可用性、休眠恢复和模型请求需另行验收，不新增 Ollama 常驻容器。

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
5. 检查人设库 Linux 路径 `/opt/fatfish/docs/persona/apple-le-full.md`；确认九个自研插件正常加载。共享数据包已安装到 Python 环境，不依赖相邻插件导入。在原生 TTS 中显式添加 `fatfish_siliconflow_tts`，填写密钥和 voice，检查 speed=1.1 后选择为语音合成提供商；Edge TTS 可保留备用，插件不自动切换声音。
6. 在 AstrBot 插件市场安装 `meme_manager` 和所需的 `proactive_chat`，或恢复已备份的源码与数据。主动消息仅在配置了目标会话后启用。
7. 在主人私聊验证公开／私人记忆隔离、离线时段、角色设定、语音发送与转写、表情语义和 B 站标签学习。`meme_manager` 的视觉描述和语义索引使用社区插件原生任务，需配置实际可用的视觉与向量模型。
8. 在 story 配置中填写投稿标签和已确认的分区 ID，用 `/视频 制作 <公开话题>` 获取预览。只有主人在同一私聊发送 `/视频 确认 <编号>` 才提交该次成片；更新投稿配置后用 `/视频 预览 <旧编号>` 获取新的编号并重新确认。超时或状态未确认时先检查 B 站稿件列表，不能自动重投。现有画面仍使用项目模板素材，投稿前检查画面、字幕和音乐。
9. 主人提供 vault 后，给 AstrBot 添加该目录的只读挂载，例如 `/srv/notes:/opt/fatfish-vault:ro`；将 Obsidian 插件 `vault_path` 设置为容器路径 `/opt/fatfish-vault`，填写实际向量模型 ID 和主人身份，再开启同步。保持独立知识库，不加入全局 `kb_names`；用 `/知识库 同步`、主人私聊检索和其他会话拒绝访问完成验收。
10. 用 `/steam 620` 检查公开价格查询。若商店返回 403，给插件配置容器可达的 HTTP 代理，重载并验证；本机 PC 的回环代理地址不能直接写入服务器容器。

轮询与生活动态真实发布在相关账号验收后分别开启。视频审批、私人知识库访问不因成长记录或模型意愿而放宽。

## 媒体与运行验收

```bash
docker compose -f deploy/compose.yaml exec astrbot python -m fatfish_video doctor
docker compose -f deploy/compose.yaml exec astrbot /opt/bili-venv/bin/bili --help
docker compose -f deploy/compose.yaml exec astrbot python -m fatfish_video render /opt/fatfish/examples/single.json --output /opt/fatfish/outputs/server-single.mp4
```

输出保存在 `deploy/state/outputs/`。确认中文字体、声音和画面后再用于正式内容。AstrBot 的进程重启由 Compose 处理；账号风控、验证码或登录失效需要本人处理，不由重启循环解决。

日常保留 `state/astrbot`、`state/napcat`、`state/qq` 和所需成片。复制 SQLite 前停止相关服务，或使用 SQLite 的备份接口；不要只拷贝正在使用的单个 `.db` 文件而忽略 WAL。部署配置未自动清理成片，磁盘保留天数由你在服务器验收时确定。
