# 鲸鲸工作台与插件配置

项目继续使用同一个 DSH 数据目录 `D:/DSHData`。鲸鲸的本机工作区为 `D:/DSHData/whale-work`，里面的 `Projects` 用于文件和项目，`Notes` 用于 Obsidian，`Bilibili` 用于视频资料。微信、QQ 和 B 站保持独立的平台身份与会话权限。

## 人设、权限与运营

新会话菜单只显示一个「鲸鲸」，可聊天、使用记忆和知识库、处理日常任务。内部保留微信使用的 `whale-social` 和桌面使用的 `whale-lifepilot`，旧会话继续使用原绑定。通过原生注册表验证了两个 ID 的解析，并在日常桌面验证了菜单显示。

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

Windows MCP 0.8.8 使用 D 盘的本机 stdio。直接握手列出 17 个工具，只读 `ControlStatus` 通过。隔离 Electron 宿主又验证了两步握手，`server/discover` 后是 `tools/list`，注册 17 个工具约耗时 11.7 秒。载体和 desktop 覆盖配置的启动上限已调到 25 秒。日常 DSH 重启后仍为 0 个，注册问题可在交互桌面探测通过时复现。生产启动跟踪因文件写入权限未生效，原配置已通过哈希核对。逐会话授权继续由 DSH 管理。

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

## 与 dsh-dafeiyu 对比

[dsh-dafeiyu v0.1.23](https://github.com/QCYTSN/dsh-dafeiyu/releases/tag/v0.1.23) 随 DSH 启动独立桌宠窗口，读取会话事件来显示任务阶段、实际待办数量和多个会话的状态。已核对本机 `dsh-pet` 0.4.3 源码，它已经优先处理等待确认和错误，并从真实待办取当前步骤。上游 [Reducer](https://github.com/QCYTSN/dsh-dafeiyu/blob/v0.1.23/src/companion-reducer.js) 更值得参考的是多会话摘要、已完成和总待办数量，以及缺数据时仅显示阶段。鲸鲸现有的 `dsh-pet` 管角色、互动、心情与碎碎念，FatFishLife 管人设、记忆、知识库、日记和跨渠道工作流。桌宠与余额查询已有重叠，本次保留现有桌宠。上游说明 Windows 原生助手首次解包约 100 MB，复用代码和素材须核对各自的 [授权与来源](https://github.com/QCYTSN/dsh-dafeiyu/blob/v0.1.23/ASSET_LICENSE.md)。

## 按功能找对标项目

GitHub Star 为 2026-11-21 仓库页面显示值，取近似数。用它看项目关注度，复用选型还要看功能是否匹配、是否有可核对的实现、许可和同版宿主验证。

| 鲸鲸能力 | 对标项目 | 借鉴点 |
| --- | --- | --- |
| 桌宠与任务提示 | [dsh-dafeiyu](https://github.com/QCYTSN/dsh-dafeiyu) | 现有 `dsh-pet` 已有状态优先级与真实待办当前项。借鉴多会话摘要、完成数／总数，以及缺数据时回退到阶段。通知从现有事件生成，无需额外模型。 |
| B 站选片、日报与推荐 | [dsh-bili-scroll](https://github.com/c1overzz/dsh-bili-scroll) 约 1.5k、[dsh-bili-whale](https://github.com/Alterssss/dsh-bili-whale) 约 1.1k | 前者对标专题选片、去重、日报和推荐命中，后者是已用的养鱼上游，对标作息、后台活动、私信与日记。当前链路仍要求真实画面证据，另外用已有字幕理解讲解。 |
| B 站互动、草稿和发布 | [dsh-bilibili-dafeiyu](https://github.com/XiaoZheBrother/dsh-bilibili-dafeiyu)、[bilibili-api](https://github.com/Nemo2011/bilibili-api) 约 4.2k | 工作台对标互动历史、草稿版本、审核与发布记录。`bilibili-api` 是接口层对照。沿用 `bili-cli` 的投递回执，制作仍走 Updream 和现有成片审批。 |
| B 站预算与故障 | [dsh-bili-pond](https://github.com/YOYOLnFu/dsh-bili-pond) | 关注按阶段显示失败、日报回查、分开管理评论和私信开关。转写配额是它的实现，鲸鲸关注视觉与模型的实际开销。 |
| 人设、记忆、知识库 | [dsh-agent-memory](https://github.com/Culeot/dsh-agent-memory)、[Hermes Agent](https://github.com/NousResearch/hermes-agent)、[现有人设对照](DSH_PERSONA.md) | 相关记忆按需注入，跨会话保持身份范围。可复用的工具经验保留来源与适用条件，和人设固定规则分开。SQLite 和 Obsidian 继续承担存储。 |
| 模型、额度和费用 | [LiteLLM](https://github.com/BerriAI/litellm) | 借鉴每条路由的实际成本、预算、失败原因和有限回退验证。鲸鲸的默认模型与人工切换规则由现有控制层维护。 |
| 渠道与媒体 | [渠道与核心](DSH_CHANNELS-20261111.md)、[微信主人私聊能力](WECHAT_OWNER_CAPABILITIES.md) | 以渠道实际规范和原生工具回执验收会话、文字、图片、语音、表情。权限在执行端校验，媒体的降级与重试按一次回复计。 |
| Windows、浏览器和其他工具 | [Windows MCP](https://github.com/CursorTouch/Windows-MCP)、[Playwright MCP](https://github.com/microsoft/playwright-mcp) | 桌面和浏览器各用自己的工具范围。分别检查协议握手、工具注册、逐会话授权和只读调用。平台回执由对应适配器维护。 |

本轮已把 B 站推荐回执细分为暂停、分镜不可用、分析没有产出可核对的画面依据。候选加载、分镜或模型分析期间收到暂停时，返回暂停原因。验证覆盖权限、去重、失败停发和单批模型次数，源码单元 7 项全部通过。日常宿主尚未换包。

### 11 月 22 日实施

- `operations_overview` 的回执视图展示 B 站候选、入围、取到分镜和生成有效推荐四个计数。届时实际私信与评论仍以平台回执判定。
- 同一视图读取每项后台任务的实际模型、输入输出和缓存 Token。HTTP 失败只记录状态码，服务端没返回 Token 时字段缺省。后台模型仍按现有单次预算执行。参考 [DeepSeek 响应规范](https://api-docs.deepseek.com/api/create-chat-completion/) 与 [LiteLLM 用量记录](https://docs.litellm.ai/docs/proxy/cost_tracking)。
- 查询型共享记忆使用已存在的词项计分，保留得分至少为最高分一半的条目。无查询的最近记录、平台和完整会话边界沿用原规则。参考 [dsh-agent-memory 相对得分阈值](https://github.com/Culeot/dsh-agent-memory)。
- 桌宠复用 dsh-pet 的 `todo/write`、状态优先级和界面气泡，在现有步骤前加真实完成数和总数。原生待办已完成、缺少清单或包含未知状态时回退到原有呈现。保持现有上游代码和素材许可声明。隔离 DSH 从状态接口读回 `1/3 获取分镜`。参考 [dsh-dafeiyu 的会话事件实现](https://github.com/QCYTSN/dsh-dafeiyu/blob/v0.1.23/src/companion-reducer.js)。
- 技能候选在已有人工审核入口展示三个不同的任务时段，供用户查找当时的运营回执。参考 [Hermes Agent 的学习闭环](https://github.com/NousResearch/hermes-agent)。

控制层候选已通过官方管理器隔离安装和宿主加载。归档内直接运行推荐替身验证了 10 万播放门槛、无分镜跳过和服务端用量读回。桌宠候选通过隔离原生事件验收。日常 DSH 使用工作区中的 MCP 源码，当前还有并发的未提交改动，两个候选的生产换包与重启等待这些改动进入同一次验收。

## DeskBox 小组件

使用 [DeskBox 官方 MCP](https://github.com/Tianyu199509/deskbox-agent)，通过 Windows 当前用户下的 `DeskBox.exe --mcp` 接入 DSH 原生 stdio 客户端。配置只挂在本机「鲸鲸」桌面 preset，注册八个工具。仓库的指南、示例和配套 Skill 采用 MIT 许可，本次直接使用 DeskBox 自带的 MCP 服务。

先用 `deskbox_get_widget_spec` 的 `compact` 模式读当前规范，再用 `deskbox_validate_manifest` 验证。需要看效果时，用 `deskbox_upsert_widget` 暂存并凭 `stageId` 请求预览。组件提交沿用 DeskBox 的原生审批，覆盖现有组件、清除数据或添加脚本时由宿主本地确认。

2026-11-24 本机 DeskBox 1.6.0 的 MCP 握手、八个工具列表、只读规范和工坊状态均通过。隔离 DSH 使用模拟模型调用了真实 DeskBox 的规范工具，并验证其他会话无工具且不能直接执行。日常 desktop 配置已写入并读回，只新增本机 preset 中的一条 MCP 配置。微信、B 站和 QQ 的真实账号会话未参与验收。

可在鲸鲸的 DSH 工作台测试「用 DeskBox 设计一个鲸鲸待办小组件，先验证格式并生成预览，等我确认后再提交」。


11/24 微信复查发现两轮 DeskBox 任务都在未挂 MCP 的入口内查找工具，最后触发旧 12 步限制。新版微信包在认证主人的直接 DeskBox 任务中提供查规范、校验、暂存和预览。提交在 DeskBox 工坊完成。主人常规任务沿用 DSH 的原生步数。连续工具失败后最多留一次无工具说明，保留工具名、失败类别和步数日志。遇到供应商错误时直接停止。

日常微信包已由 DSH 官方包管理器替换并重启读回。隔离 DSH 访问真实 DeskBox 并拒绝微信提交，另用本机三项占位文本校验、暂存并渲染 PNG。真实微信消息未用于自动验收。

飞书按请求读取可复用官方远程 MCP 的 `fetch-doc`，由主人在私聊发送文档链接，按飞书授权范围读取。这个需求适合按需触发。定时读取可另用自建应用，数据范围由应用的页面权限决定。当前未配置可用于真实文档读取的飞书授权。[飞书官方工具列表](https://open.feishu.cn/document/mcp_open_tools/supported-tools)

## Linux 试运行容量

以下是 API 推理场景的规划值。轻量单实例最低按 2 vCPU、4 GiB 内存和 40 GB SSD 规划，适用于 Headless DSH、FatFish 核心、SQLite 和少量低并发接入。要同机运行多个接入、常驻任务和现有容器，建议 4 vCPU、8 GiB 内存和 80 GB SSD。跑本地模型或持续处理视频时，按模型和任务单独测峰值。

RackNerd 实测 2 vCPU、2,468 MiB 内存，采样只有 40 MiB 可用内存并持续换页。DeepSeek 网关未鉴权探测耗时约 323–368 毫秒，适合先做小规模直连验证。以上数据不能估算模型首字延迟。DeskBox 桌面宿主继续在 Windows 运行，Linux 负责无界面工作。现阶段无需国内中转。
