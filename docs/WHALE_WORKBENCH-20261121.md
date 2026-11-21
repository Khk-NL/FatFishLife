# 鲸鲸工作台与插件配置

项目继续使用同一个 DSH 数据目录 `D:/DSHData`。鲸鲸的本机工作区为 `D:/DSHData/whale-work`，里面的 `Projects` 用于文件和项目，`Notes` 用于 Obsidian，`Bilibili` 用于视频资料。微信、QQ 和 B 站保持独立的平台身份与会话权限。

## 人设、权限与运营

新会话菜单只显示一个「鲸鲸」，提供桌面 LifePilot 能力。内部保留微信使用的 `whale-social` 和桌面使用的 `whale-lifepilot`，旧会话继续使用原绑定。通过原生注册表验证了两个 ID 的解析，并在日常桌面验证了菜单显示。

- 桌面和微信从结构化人设读取共用说话规则，B 站使用同一份人设文本。闲聊尽量在 50 字以内，主要用逗号和换行，自称本鱼或人家，避开指定套话。分析、代码和来源链接按任务需要保留。
- 自动推荐与学习筛选已知播放量至少 10 万的片源。推荐用 `dsh-video-storyboard` 提供的真实画面证据，失败时跳过。订阅与评论工具复用 `dsh-bili-whale`，公开评论只写感想，统计留在私信或报告。`dsh-see-now` 是实时屏幕输入，`dsh-video-storyboard` 是单个视频分析，两者用途分别保留。
- 桌面工作台配置独有的 Windows MCP，保留界面快照、点击、输入、截图等 17 个工具。通用脚本、文件和系统权限走 DSH 自有入口，避免重复。已认证微信仍通过明确的工作流申请跨平台或桌面动作，公开评论和群聊各自按最小权限访问工具。投稿、直播、付费和发送私人文件需确认具体目标。
- `FatFish 控制`下可切换峰闲时策略，也可保留并调整星期、开始和结束时刻。关闭后时段留存，生效策略的忙碌窗口为空。部署候选按用户的最新使用意图关闭峰闲限制。
- 笔记区已通过 KNJ Obsidian 自带的 VaultStore 初始化。基础 Obsidian 插件负责读写笔记，KNJ 提供索引及知识图谱，ACP 供 Obsidian 内发起 DSH 会话。ACP 已完成 `initialize`、`session/new`，使用长会话模式并禁用无工具审批的 spawn 降级。交互式笔记编写要在 Obsidian 打开该目录后核验。

## 模型和额度


已绑定主人的微信文字默认使用 DeepSeek。赠送或试用积分至少 50 且模型可用时，走 WorkBuddy 的 DeepSeek-V4.1 Flash，其余情况走官方 DeepSeek API。

- `/model` 或「你现在用的是什么模型」查询本会话最近一次确认送达的模型。配置里的默认模型、失败的发信或其他会话都不产生这条记录。
- `/quota` 或「Codex 额度、WorkBuddy 积分还有多少」读取两家额度。Codex 分别显示五小时与七天窗口，额度不可用时如实说明。查询不调用推理。
- `/model codex` 或「切换到 GPT」才会主动切到 GPT-6.2 Sol 中档。默认要求五小时余量至少 80%、七天至少 50%。关闭插件、额度不足或数据到期时退回 DeepSeek，重新启用 GPT 仍需明确指令。
- `/model deepseek` 或「切回 DeepSeek」恢复默认。门槛可在「设置 → FatFish 控制 → 自动选模型」调整。
- `/diary` 能查询日记写入状态，有日期时用北京时间核对。日记正文和调度回执分开读取。

复用 [dsh-connect-workbuddy](https://github.com/dingminhua/dsh-connect-workbuddy) 5.25.2 与 [dsh-codex-subscription](https://github.com/WSL043/dsh-codex-subscription) 3.2.27 本机认证和额度接口，适配归档保留 MIT 许可与署名。WorkBuddy 自动签到保存为国内单账号，2026-11-21 查到已领 100 积分，5,045.78 分为本次只读余额。

Windows MCP 使用 D 盘的 Windows-MCP 0.8.8。正常退出后已用插件写入并读回桌面 stdio 桥，保留四项排除和逐会话授权。此前隔离原生宿主验证了 17 个工具，未授权调用会被拒绝。此轮实际桌面识别到 0.8.8，工具数为 0。原生诊断复现 `No active interactive desktop for physical input control`，Windows 拒绝读取当前输入桌面。需从可用的 Windows 桌面打开 DSH 后检查工具数。

## QQ 视频核对

本次手动读取 [《小号别再被封了！QQ机器人风控防范指南》](https://www.bilibili.com/video/BV1W2nr6yERy/)，使用现有 Video Storyboard 的命令行通道抽看 12 格。视频在约 1:09 区分官方与社区通道，约 11:04 讨论群聊触发与回复节奏。官方 QQ 条款同时限制未授权第三方登录、自动发送和未经同意采集数据，降低频率无法改变通道是否获授权。原 QQ 暂停保持，个人账号方案选「鲸鲸起草，用户在官方 QQ 手动核对并发送」，只提供用户主动挑选的对话，避免把聊天库接进记忆系统。参考 [QQ 软件许可及服务协议 8.2](https://ti.qq.com/agreement/index.html)。

## 腾讯办公接入

- 腾讯文档有正式的远程 MCP，入口 `https://docs.qq.com/openapi/mcp`。账号在官方授权页单独生成令牌，DSH 可用原生 MCP 客户端发送标准 `Authorization` 头。服务有读写工具，接入时应先放到本机工作台并只开放查询。部分能力可能需要现有会员权益。 [腾讯文档 MCP](https://developer.cloud.tencent.com.cn/mcp/server/11803)
- 腾讯会议向个人和专业账号开放官方 MCP 技能，支持查会议、录制和纪要，也含预约、修改与取消。官方封装依赖会议令牌，可由 DSH 的本机 MCP 客户端接入，授权后从只读会议查询验证。 [腾讯会议 MCP](https://meeting.tencent.com/support/articles/14/index.html)
- Buddy One 官方说明覆盖账号关联、资料检索和适用产品的积分共用。目前未核实面向 DSH 的整套通用授权入口。腾讯文档和会议可以按上述各自账号接口接入。 [Buddy One](https://www.workbuddy.cn/buddyone/)

## 复用与验收

- [dsh-bili-whale](https://github.com/Alterssss/dsh-bili-whale) 保留 MIT 原包、监听、私信和评论出口，只适配人设、限额和选片。参考 [dsh-bilibili-dafeiyu](https://github.com/XiaoZheBrother/dsh-bilibili-dafeiyu) 对工作区、草稿和直播的分层，及 [dsh-dafeiyu-life](https://github.com/minedalang/dsh-dafeiyu-life) 的意图和真实平台回执。现有插件的直播功能是监听，开播需要正式平台权限、推流链路和单独验收。投稿仍通过项目已接入的 Updream 成片预览和审批。
- Windows MCP、Obsidian ACP、KNJ、基础 Obsidian 和 WorkBuddy 使用其各自的上游 MIT 包，保留许可证；未引入账号池或伪装客户端。优先使用 [Codex 官方 App Server](https://learn.chatgpt.com/docs/app-server) 的额度查询。
- 桌宠和余额挂件分别负责桌面互动与余额展示，保留。原 Distill 不在当前 profile 包列表，旧回滚包不算运行中的插件。工具管理面板和逐轮工具过滤职责不同，保留现有用户配置。
- B 站人设文件已备份并读回校验。Windows MCP 与 Obsidian ACP 使用本机协议测试，未触发付费推理、屏幕控制、实际评论或直播。桌面 profile 需要在正常退出窗口后通过官方包管理器升级，升级后再核验工作区、设置开关、权限范围以及 B 站与微信的实际回复。
