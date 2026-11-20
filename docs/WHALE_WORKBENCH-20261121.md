# 鲸鲸工作台与插件配置

项目继续使用同一个 DSH 数据目录 `D:/DSHData`。鲸鲸的本机工作区为 `D:/DSHData/whale-work`，里面的 `Projects` 用于文件和项目，`Notes` 用于 Obsidian，`Bilibili` 用于视频资料。微信、QQ 和 B 站保持独立的平台身份与会话权限。

## 人设、权限与运营

- 桌面和微信从结构化人设读取共用说话规则，B 站使用同一份人设文本。闲聊尽量在 50 字以内，主要用逗号和换行，自称本鱼或人家，避开指定套话。分析、代码和来源链接按任务需要保留。
- 自动推荐与学习筛选已知播放量至少 10 万的片源。推荐用 `dsh-video-storyboard` 提供的真实画面证据，失败时跳过。订阅与评论工具复用 `dsh-bili-whale`，公开评论只写感想，统计留在私信或报告。`dsh-see-now` 是实时屏幕输入，`dsh-video-storyboard` 是单个视频分析，两者用途分别保留。
- 桌面工作台配置独有的 Windows MCP，保留界面快照、点击、输入、截图等 17 个工具。通用脚本、文件和系统权限走 DSH 自有入口，避免重复。已认证微信仍通过明确的工作流申请跨平台或桌面动作，公开评论和群聊各自按最小权限访问工具。投稿、直播、付费和发送私人文件需确认具体目标。
- `FatFish 控制`下可切换峰闲时策略，也可保留并调整星期、开始和结束时刻。关闭后时段留存，生效策略的忙碌窗口为空。部署候选按用户的最新使用意图关闭峰闲限制。
- 笔记区已通过 KNJ Obsidian 自带的 VaultStore 初始化。基础 Obsidian 插件负责读写笔记，KNJ 提供索引及知识图谱，ACP 供 Obsidian 内发起 DSH 会话。ACP 已完成 `initialize`、`session/new`，使用长会话模式并禁用无工具审批的 spawn 降级。交互式笔记编写要在 Obsidian 打开该目录后核验。

## 模型和额度

WorkBuddy 国内和国际账号目前都返回未登录。在官方 WorkBuddy 客户端登录自己的账号，到账号页看可用积分、积分明细及页面显示的官方活动，再打开 DSH 的 WorkBuddy 设置选择对应区域，重新检测或完成浏览器登录，然后刷新实际模型和积分倍率。同一笔预算下的效果需按鲸鲸的中文聊天、工具调用和视频理解任务比较，模型名称或倍率单独无法证明性价比。

Codex CLI 能核实订阅登录，当前 App Server 初始化 SQLite 状态时被本机文件权限拦截，5 小时额度和账号模型列表无法读回。DSH 的 Codex 订阅插件有独立浏览器登录，在 DSH 完成登录后检查账号真实目录和额度。路由条件是同一个已选账号的 300 分钟窗口剩余严格大于 80%，并且目录同时支持 `gpt-6.2-sol` 和 `medium`。WorkBuddy 只在积分有可核实读数、模型对比优于 DeepSeek 且支持当前任务时进入候选。生产自动切换未启用，当前保留现有 DeepSeek 路由。订阅权益和 OpenAI API 计费分别管理。

## 复用与验收

- [dsh-bili-whale](https://github.com/Alterssss/dsh-bili-whale) 保留 MIT 原包、监听、私信和评论出口，只适配人设、限额和选片。参考 [dsh-bilibili-dafeiyu](https://github.com/XiaoZheBrother/dsh-bilibili-dafeiyu) 对工作区、草稿和直播的分层，及 [dsh-dafeiyu-life](https://github.com/minedalang/dsh-dafeiyu-life) 的意图和真实平台回执。现有插件的直播功能是监听，开播需要正式平台权限、推流链路和单独验收。投稿仍通过项目已接入的 Updream 成片预览和审批。
- Windows MCP、Obsidian ACP、KNJ、基础 Obsidian 和 WorkBuddy 使用其各自的上游 MIT 包，保留许可证；未引入账号池或伪装客户端。优先使用 [Codex 官方 App Server](https://learn.chatgpt.com/docs/app-server) 的额度查询。
- 桌宠和余额挂件分别负责桌面互动与余额展示，保留。原 Distill 不在当前 profile 包列表，旧回滚包不算运行中的插件。工具管理面板和逐轮工具过滤职责不同，保留现有用户配置。
- B 站人设文件已备份并读回校验。Windows MCP 与 Obsidian ACP 使用本机协议测试，未触发付费推理、屏幕控制、实际评论或直播。桌面 profile 需要在正常退出窗口后通过官方包管理器升级，升级后再核验工作区、设置开关、权限范围以及 B 站与微信的实际回复。
