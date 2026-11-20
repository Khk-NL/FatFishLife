# 小鱼人设与按需渠道

## 从哪里编辑

`dsh/persona/whale.json` 是新版人设的可编辑源。核心人格、称呼关系、行为策略和上下文开关各有独立字段。JSON 便于校验、比较和分享，Markdown 用于预览与 B 站现有的人设入口。账号、凭据、权限配置和记忆保存在原位置。人设字段本身没有权限授予能力。

在仓库根目录运行：

```powershell
npm --prefix dsh/persona/editor ci --ignore-scripts
npm --prefix dsh/persona/editor start
```

访问 [本地人设编辑器](http://127.0.0.1:7418/)。可以导入和导出 v1 JSON，切换桌面、微信、QQ 和 B 站的注入预览，并复制或下载 Markdown。浏览器表单与 DSH 渲染使用同一份规则。编辑器只监听本机回环，运行时资源来自本机。

现有日常配置可以生成候选以供审阅：

```powershell
python scripts/sync_persona_dsh.py --card dsh/persona/whale.json --dry-run
python scripts/sync_persona_dsh.py --card dsh/persona/whale.json --candidate-dir outputs/persona-candidate
```

生成命令只定位 `whale-social` 的人格区块，并另外生成 B 站版。该候选包含日常 profile 的本机设置，留在私有输出目录。对外分享使用编辑器导出的 JSON。原 Markdown 人设作为迁移来源及回退资料。

## 运行时如何选择信息

| 内容 | 加载与授权 |
| --- | --- |
| 人格、称呼与行为 | DSH 现有预设入口加载稳定前缀。群聊规则仅进入群聊可用的 QQ 或桌面预览。 |
| 工具 | 新本机预设从 DSH 当前步实际声明的工具生成分类提示，附上真实工具名。隐藏压缩、解压、上下文搜索、ACP 状态，并在执行端挡住伪造调用。工具参数与最终权限仍由 DSH/MCP 校验。 |
| 记忆、知识、活动与状态 | 延续现有 FatFish 记忆库和 MCP。微信适配根据本条消息按需读取活动、成长片段、相关学习语料和全局心情，只向已绑定的主人提供，轻量规则无需模型。普通闲聊不读这些资料。 |
| 审核与边界 | 只从可信渠道身份获取权限。个人会话、群和平台之间沿用已有隔离。外部资料作为数据处理，底层调度和协议细节由宿主管理。 |

前缀候选为 607 字符，现有日常人设样本为 7,875 字符。该候选用于隔离体验和比较。它的字符数与模型效果、扣费是不同指标，实际人设风格需由使用者确认。

## 按需选择渠道

```powershell
python scripts/plan_dsh_channels.py --channels wechat bilibili
python scripts/plan_dsh_channels.py --channels wechat --home outputs/fish-wechat
```

第二条命令生成一个全新 DSH 数据目录，可把编辑器导出的卡放到该目录的 `persona.json`。传入 `--cli` 与每个选中渠道对应的 `--archive 渠道=本机归档.tgz` 后，脚本通过 DSH 随包插件管理器安装已选归档。OneBot 复用项目现有适配包。发布官方 QQ 渠道时，随发布物另附带 Tencent SDK 的已验证 FatFish 适配归档；只有普通 OneBot 的包不支持这一选项。微信包用 `scripts/prepare_wechat_shared_context.py`，B 站沿用现有审查通过的 `dsh-bili-whale` 归档。若默认包存储无法访问，`--store-dir` 可指向有权限的现有 pnpm store。

| 选择 | 复用入口 |
| --- | --- |
| `wechat` | 腾讯 iLink 服务，经由现有 FatFish 微信适配，主人白名单、固定命令与单轮限额沿用。 |
| `qqbot` | 腾讯官方 QQ Bot SDK，经由同一个 FatFish QQ 桥。配置模板中的账号初始关闭。 |
| `snowluma`、`napcat` | 外置进程使用 OneBot v11，经由同一个 QQ 桥。选择一种 QQ 传输即可。FatFish 分发不包含这两个进程。 |
| `bilibili` | 复用现有 B 站养鲸和 bili CLI。B 站运行时按现有路径读取生成的 Markdown 人格。 |

按需档案初始只准备和安装组件，渠道均关闭。配置对应账号与授权后，可在该档案单独启用和验证。可选 `--mcp-python` 把现有 FatFish MCP 挂到本机专属预设，默认使用该档案内的记忆库。要共用已授权数据库，可另外指定 `--memory-db`。已有适配器仍各自负责传输、去重和回执，模型可用的能力继续遵循 [MCP 接入规范](MCP_INTEGRATION.md)。

选装任一 QQ 传输时，额外用 `--control-archive` 提供现有 FatFish 控制层，供 QQ 桥加载权限策略。初始化后的控制层和 QQ 桥都关闭。启用前先填写控制层账号身份及对应渠道认证，并保留静默作启动验证。

## 开源说明

| 项目 | 采用方式 |
| --- | --- |
| [JSON Editor](https://github.com/json-editor/json-editor) | 本地编辑器直接依赖 `@json-editor/json-editor@2.17.4`，MIT。该上游处于维护模式；依赖和许可证由 npm 锁定并随包保留。 |
| [DSH](https://github.com/deepseek-ai/deepseek-harness) | 直接调用原生预设、提示词注册和工具执行器，版本以实际宿主验证为准。 |
| [dsh-persona-dafeiyu](https://github.com/huaizhuanghub/dsh-persona-dafeiyu) | MIT。参考人设的导入、管理与作用域。 |
| [dsh-agent-memory](https://github.com/Culeot/dsh-agent-memory) | MIT。参考相关性阈值与有界注入，底层使用已有 FatFish 记忆库。 |
| [whale-persona](https://github.com/shena2024/whale-persona) | MIT。参考人格、行为和记忆审核分离。 |

最后三项为实现参考，未复制其源码。渠道沿用已有上游归档与许可证，已有复用关系见 [上游依赖锁](../dsh/upstream-lock.json)。
