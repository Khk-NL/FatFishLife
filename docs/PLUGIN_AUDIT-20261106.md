# DSH 插件清点（2026-11-06，只读）

本次只读 profile 的依赖、bundle/patch 拓扑，以及实际安装包公开 metadata。未输出配置正文、环境变量、凭据或日志，未安装、卸载、更新或改写 profile。

## 当前基线

- 宿主 EXE FileVersion 和内置 `@deepseek-ai/dsh` 均为 **0.2.2-rc.1**；内置 Node 24.21.0、Cordis 4.1.0、Schemastery 3.19.0、dsh-tools/dsh-agent/dsh-settings 0.2.2-rc.1。
- profile 声明 **22 个直接依赖、23 个 bundle**（含 2 个内置 bundle）。其中 21 个外部依赖有安装包；`dsh-pet` 缺包且未列入 bundle。
- “bundle 接入”仅表示配置拓扑包含它；“profile 覆盖”仅表示 patch 对该条目有显式配置。两者都不能证明运行时已成功加载、设置已完整或真实账号可用。本次未读取运行时插件注册表，所有包的实时 loaded 状态均待运行证据。
- 本轮主线已对新适配源码完成隔离宿主验证，但不能用该结果替代旧生产包 metadata。QQ 仍有账号暂停标记，不做真实账号测试。

## 依赖与配置

表内“范围未声明”表示包没有给出可据此保证当前宿主兼容的 DSH 版本约束，不代表不兼容。

| 分类 | 插件 / 实装版本 | 配置状态 | 来源及兼容声明 |
| --- | --- | --- | --- |
| QQ 通道 | `dsh-onebot-qq` 0.9.6 | bundle + profile 覆盖 | 本地适配归档存在；声明含 0.2.x 范围；真实 QQ 暂停 |
| 生活控制 | `dsh-fatfish-life` 0.1.0 | bundle + profile 覆盖 | 生产旧 metadata 仍锁 dsh-tools 0.2.1-rc.3、Cordis ~4.0.5、Schemastery ~3.18.5；源码 0.1.1 的新适配尚未部署 |
| 记忆/资料 | `dsh-knowledge-base` 0.1.5 | bundle，包内提供配置 | registry；DSH peers `*`；未独立验证 UI/导入 |
| 记忆/资料 | `dsh-obsidian` 0.2.6 | bundle，无 profile 覆盖 | registry；DSH peers `*`；不能据此判断 vault 已配置 |
| 上下文 | `billion-context` 0.1.212 | bundle，覆盖宿主压缩等条目 | registry；DSH 范围未声明；与原生压缩的分工需统一 |
| 上下文观察 | `dsh-context` 0.78.0 | bundle，无 profile 覆盖 | registry；宽范围，兼容表仅显式列 0.2.0/0.2.1 的旧 rc；当前版未专项验收 |
| 经验沉淀 | `@loserfox/distill` 0.1.0 | bundle + profile 覆盖 | **自引用 file 源**；多个 DSH peers 仍是 0.0/0.1 旧范围，与当前宿主不一致 |
| 错误记录 | `dsh-fail-logger` 0.5.2 | bundle + profile 覆盖 | **自引用 file 源**；DSH 范围未声明 |
| 工具增强 | `dsh-ops` 0.4.4 | 4 个 mode + discovery 接入；compat/panel/tui 显式禁用 | registry；engine/peer 声明 `<0.2.2-0`，排除当前宿主 |
| 搜索 | `@liustack/modsearch` 5.10.11 | bundle，无 profile 覆盖 | **自引用 file 源**；DSH 范围未声明；未核验联网服务 |
| 视觉 | `@liustack/modlens` 3.27.2 | bundle，无 profile 覆盖 | registry；DSH 范围未声明；未核验外部 CLI/登录依赖 |
| B 站文本 | `dsh-plugin-bilibili` 0.2.4 | bundle，包内提供配置 | 本地适配归档存在；多个 DSH peers 精确锁 0.2.1-rc.3，未声明当前宿主兼容 |
| B 站养鱼 | `dsh-bili-whale` 0.4.6 | bundle，无 profile 覆盖 | `link:D:/Code/plugins/dsh-bili-whale` 目标存在；DSH 范围未声明；不等于真实账号或自动任务已验收 |
| 主动搭话 | `dsh-speak-up` 0.2.7 | bundle，无 profile 覆盖 | 本地适配归档存在；DSH 范围未声明；与生活控制主动发言的职责需核对 |
| 心情 | `dsh-feiyu-mood` 0.8.1 | bundle，无 profile 覆盖 | 本地适配归档存在；DSH 范围未声明；需核对与 FatFish 心情数据的关系 |
| 表情 | `dsh-nekowhale-stickers` 1.1.1 | bundle + profile 覆盖 | 本地适配归档存在；声明较宽；与桥已有表情调用链相连 |
| 插件发现 | `dsh-find-plugin` 0.4.0 | bundle，无 profile 覆盖 | 本地适配归档存在；dsh-tools 精确锁 0.2.1-rc.3 |
| 插件市场 | `dshmarket` 1.73.1 | bundle，无 profile 覆盖 | registry；DSH settings peer 有多个旧范围；需按宿主实际预发行版规则验收 |
| 维护 | `dsh-unlag` 1.14.12 | bundle，同时启用 HMR 条目 | registry；声明 DSH >=0.2.0-rc.1；未测试此次实际刷新 |
| 安全 | `cc-safety-net` 2.7.0 | bundle | registry；DSH 范围未声明；OpenCode peers 是 optional，不应误判为缺失硬依赖 |
| 视频观察 | `dsh-video-storyboard` 0.4.3 | bundle，无 profile 覆盖 | registry；tools 版本下界较宽；不是 Updream 制作链，也不是 B 站只读文本工具的替代 |
| 桌宠 | `dsh-pet` 声明 ^0.3.8，实装缺失 | 未列 bundle | `node_modules/dsh-pet` 不存在；不能沿用历史“已恢复”结论 |

## 可确定的问题与取舍建议

1. **先处理安装可复现性。** `modsearch`、`distill`、`fail-logger` 的 `file:node_modules/...` 指向它们自身，未来重新安装可能丢失安装源。应使用已经保留的独立源或正规版本源，但本清点没有执行替换。其余本地适配归档和 B 站 link 目标本次均存在。
2. **兼容声明需要分批对齐。** 旧 find-plugin、ops、bilibili 的不匹配仍在；distill 的旧 peers 也需单独核验。FatFish 生产包保留旧声明，而新源码有独立验收，不应混为一谈。运行过一次不代表未来插件管理器会接受安装；不能靠删除版本检查解决。
3. **按功能定主责，不直接按数量卸载。** 上下文由原生机制、billion-context 和 dsh-context 分别承担压缩/长上下文/观察，先确认实际介入点；记忆由 FatFish 会话库承担聊天，KB/Obsidian 作为资料源；B 站文本插件负责读，bili-whale 与 FatFish 运营需明确唯一的自动任务所有者；speak-up/生活控制和 mood/FatFish 心情应核对是否重复驱动。工具观察、错误记录、安全拦截有不同职责，不因名字相近自动视为冗余。
4. **禁用不等于废弃。** dsh-ops 的 compat/panel/tui 是显式禁用子项；没有足够证据把整个包判为废弃。没有 profile 覆盖的包可能使用包内默认值或独立设置存储，不能标成“未配置”；需后续通过对应设置/只读状态确认。
5. **桌宠先记缺失状态。** 当前缺包且未挂 bundle；全 profile 的兼容声明和自引用源问题尚在，不在本轮盲目重装。

## 证据位置与时间

- `D:/DSHData/profiles/desktop/package.json`：LastWriteTimeUtc **2026-11-05 20:17:14**。
- `D:/DSHData/profiles/desktop/cordis.patch.yml`：LastWriteTimeUtc **2026-11-05 11:35:40**。
- 生产 `node_modules/dsh-fatfish-life/package.json`：LastWriteTimeUtc **2026-11-05 14:59:03**。
- 版本和兼容字段来自上述 profile 的各安装包 `package.json`、公开 bundle patch，以及 `D:/dsh/resources/app.asar/dsh/node_modules/@deepseek-ai/` 内置包 metadata。

这些时间只证明所观察文件的落盘时间，不解释桌宠何时或为何缺失。本次未安装或加载缺包，也未读取账号凭据、接受软件协议、运行任务或发送消息。

## 官方 npm latest 复核（同日，5 次 HTTP JSON 请求）

仅获取以下五个 `latest` manifest，没有下载发行包、安装、运行或修改版本豁免。本次没有枚举全部历史版本或非 latest 标签，因此“latest 不匹配/不可查”不能外推为所有历史版本都不兼容。

当前宿主 `dsh-app-boot` 的兼容检查使用 `semver` 的 `includePrerelease:true`；先判断 `engines.dsh`，没有该字段时才判断 DSH peers。另按实际 Cordis 4.1.0、Schemastery 3.19.0 检查其声明。兼容范围匹配仅允许进入进一步验收，不能证明 API、界面或账号功能正常。

| 包 | 官方 latest 结果 | 对当前宿主的声明结论 / 可执行建议 |
| --- | --- | --- |
| `dsh-find-plugin` | [0.4.0](https://registry.npmjs.org/dsh-find-plugin/latest) | tools peers 仍只覆盖旧 0.1.x 系列，不含 0.2.2-rc.1；Cordis ^4.0.1 匹配。没有可用的 latest 升级候选；保留本地适配源码继续核验实际 API，不能直接替换声明规避检查。 |
| `dsh-ops` | [0.4.4](https://registry.npmjs.org/dsh-ops/latest) | engine/peer 的 `<0.2.2-0` 明确排除当前宿主；Cordis ^4.0.4、Node 条件匹配。仍没有可用的 latest 更新。 |
| `dsh-plugin-bilibili` | [0.2.1](https://registry.npmjs.org/dsh-plugin-bilibili/latest) | DSH peers 使用 >=0.0.1 等宽下界，按宿主规则匹配；Cordis >=4.0.0、Schemastery >=3.18.0 也匹配。但它低于本地文本工具适配包 0.2.4，不能当作原样覆盖的升级；若评估上游，需保留“不抽帧/不取媒体/不自动转写”的现有适配与验证。 |
| `@loserfox/distill` | [latest 端点](https://registry.npmjs.org/%40loserfox%2Fdistill/latest)返回 HTTP 404 | 无法取得该名称的公开 latest metadata；不能推断原因是改名、未发布还是访问范围。暂没有经过核对的公开更新候选，仍需先保存并核验现有独立源。 |
| `dsh-pet` | [0.4.3](https://registry.npmjs.org/dsh-pet/latest) | DSH peers ^0.2.0-rc.1 按宿主规则匹配当前版本，Cordis ^4.0.4 与 Node >=22.12.0 也匹配；未声明 Schemastery peer。兼容表只明确列到 0.2.2-alpha.2，未列当前 rc.1。可列为后续恢复候选，不能在当前全 profile 安装阻塞尚未处理时直接重装。 |

桌宠另声明 `react/react-dom`、`dsh-client-ui-slots`、`dsh-client-ui-primitives` 等客户端 peers；本次未在宿主常规 `node_modules` 位置找到这些包的独立 metadata。客户端可能另有供给方式，不能据此断言必然缺失，也不能把它们当作已经满足。其余所查桌宠 DSH 服务 peers 的宿主版本均为 0.2.2-rc.1；恢复前仍需插件管理器和界面专项验收。

对这五项仅查看现有包的公开入口，没有确认出可可靠定位的独立用户设置文件；桌宠实际包也不在。因此没有读取或猜测用户数据路径，未把“无 profile 覆盖”升级成“关键字段未填写”。是否已配置仍须通过各插件受支持的设置/只读状态接口确认，不能靠安装声明判断。
