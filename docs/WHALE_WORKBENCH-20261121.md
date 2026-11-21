# 鲸鲸工作台与插件配置

项目继续使用同一个 DSH 数据目录 `D:/DSHData`。鲸鲸的本机工作区为 `D:/DSHData/whale-work`，里面的 `Projects` 用于文件和项目，`Notes` 用于 Obsidian，`Bilibili` 用于视频资料。微信、QQ 和 B 站保持独立的平台身份与会话权限。

## 人设、权限与运营

- 桌面和微信从结构化人设读取共用说话规则，B 站使用同一份人设文本。闲聊尽量在 50 字以内，主要用逗号和换行，自称本鱼或人家，避开指定套话。分析、代码和来源链接按任务需要保留。
- 自动推荐与学习筛选已知播放量至少 10 万的片源。推荐用 `dsh-video-storyboard` 提供的真实画面证据，失败时跳过。订阅与评论工具复用 `dsh-bili-whale`，公开评论只写感想，统计留在私信或报告。`dsh-see-now` 是实时屏幕输入，`dsh-video-storyboard` 是单个视频分析，两者用途分别保留。
- 桌面工作台配置独有的 Windows MCP，保留界面快照、点击、输入、截图等 17 个工具。通用脚本、文件和系统权限走 DSH 自有入口，避免重复。已认证微信仍通过明确的工作流申请跨平台或桌面动作，公开评论和群聊各自按最小权限访问工具。投稿、直播、付费和发送私人文件需确认具体目标。
- `FatFish 控制`下可切换峰闲时策略，也可保留并调整星期、开始和结束时刻。关闭后时段留存，生效策略的忙碌窗口为空。部署候选按用户的最新使用意图关闭峰闲限制。
- 笔记区已通过 KNJ Obsidian 自带的 VaultStore 初始化。基础 Obsidian 插件负责读写笔记，KNJ 提供索引及知识图谱，ACP 供 Obsidian 内发起 DSH 会话。ACP 已完成 `initialize`、`session/new`，使用长会话模式并禁用无工具审批的 spawn 降级。交互式笔记编写要在 Obsidian 打开该目录后核验。

## 模型和额度

WorkBuddy 国内账号已通过现有连接器鉴权，读取到 4,600 积分与 15 个模型，国际区未登录。`workbuddy/deepseek-v4.1-flash` 是同名候选，目录显示 ×0.11。用户指定只使用每日签到获赠的积分。11 月 21 日只读查询显示当天已签到，奖励 100 积分，未返回另行计算的连签奖励。下一次从官方客户端「个人主页／成长计划」打开，核对实际签到、到账与有效期。已有余额无现金增量成本的前提是它确属可用的赠送积分，公开连接器的余额读数为合计。

模型准入以 DSH 当前直连 `deepseek-flash` 实际服务的 DeepSeek-V4.1-Flash-1017 为基线。同名候选还要验证实际版本、图片及工具能力，并在相同任务上对照质量。×0.11 是 WorkBuddy 内部积分倍率。对于版本、能力、额度或表现未知的任务，继续使用已配置的 DeepSeek。首次验收优先短样本、同工具和同输入，不使用连接器会发送大提示的测试按钮。WorkBuddy 的积分查看和目录刷新均已通过真实读操作，未自动路由或调用推理测试。参考 [腾讯 WorkBuddy](https://cloud.tencent.com/product/workbuddy)、[连接器文档](https://github.com/dingminhua/dsh-connect-workbuddy) 和 [DeepSeek 实际计费](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)。

Codex CLI 能核实订阅登录。现有 App Server 控制套接字从本进程连接失败，新起 App Server 也没有返回可用额度。DSH 的 Codex 订阅插件有独立浏览器授权，在 DSH 完成登录后检查账号真实目录和额度，凭据留在登录器内。路由资格读取同一个已选账号的 300 分钟窗口，剩余严格超过设置页阈值（默认 80%），且目录同时支持 `gpt-6.2-sol` 和 `medium`。生产自动切换未启用。订阅权益和 OpenAI API 计费分别管理。

## 可调默认值

在 `DSH → 设置 → FatFish 控制` 中调整。`运营计划` 的最低播放量默认 100,000，填 0 取消门槛，供自动推荐、B 站视频精读和微信视频报告共用。`鲸鲸说话习惯` 的闲聊和公开评论分别默认 50 字，前者为语气目标，后者在自动评论出口检查。`模型资格` 的 Codex 额度百分比用于只读资格检查。峰闲开关和时间表仍原样可调。新版归档已生成，生产桌面退出换包后显示新控件。

## QQ 视频核对

本次手动读取 [《小号别再被封了！QQ机器人风控防范指南》](https://www.bilibili.com/video/BV1W2nr6yERy/)，使用现有 Video Storyboard 的命令行通道抽看 12 格。视频在约 1:09 区分官方与社区通道，约 11:04 讨论群聊触发与回复节奏。官方 QQ 条款同时限制未授权第三方登录、自动发送和未经同意采集数据，降低频率无法改变通道是否获授权。原 QQ 暂停保持，个人账号方案选「鲸鲸起草，用户在官方 QQ 手动核对并发送」，只提供用户主动挑选的对话，避免把聊天库接进记忆系统。参考 [QQ 软件许可及服务协议 8.2](https://ti.qq.com/agreement/index.html)。

## 复用与验收

- [dsh-bili-whale](https://github.com/Alterssss/dsh-bili-whale) 保留 MIT 原包、监听、私信和评论出口，只适配人设、限额和选片。参考 [dsh-bilibili-dafeiyu](https://github.com/XiaoZheBrother/dsh-bilibili-dafeiyu) 对工作区、草稿和直播的分层，及 [dsh-dafeiyu-life](https://github.com/minedalang/dsh-dafeiyu-life) 的意图和真实平台回执。现有插件的直播功能是监听，开播需要正式平台权限、推流链路和单独验收。投稿仍通过项目已接入的 Updream 成片预览和审批。
- Windows MCP、Obsidian ACP、KNJ、基础 Obsidian 和 WorkBuddy 使用其各自的上游 MIT 包，保留许可证；未引入账号池或伪装客户端。优先使用 [Codex 官方 App Server](https://learn.chatgpt.com/docs/app-server) 的额度查询。
- 桌宠和余额挂件分别负责桌面互动与余额展示，保留。原 Distill 不在当前 profile 包列表，旧回滚包不算运行中的插件。工具管理面板和逐轮工具过滤职责不同，保留现有用户配置。
- B 站人设文件已备份并读回校验。Windows MCP 与 Obsidian ACP 使用本机协议测试，未触发付费推理、屏幕控制、实际评论或直播。桌面 profile 需要在正常退出窗口后通过官方包管理器升级，升级后再核验工作区、设置开关、权限范围以及 B 站与微信的实际回复。
