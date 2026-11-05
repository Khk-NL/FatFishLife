# QQ 上下文工具循环复核（2026-11-06）

## 结论

`compress` 被社交工具守卫连续拒绝是已修复的历史问题。当前源码与已安装 `dsh-onebot-qq/lib/runtime-adapter.mjs` 都已放行 `compress`、`decompress`、`search_context`、`acp_status`；本轮不重复改运行逻辑，只补针对性回归。账号暂停标记 `data/.qq-account-paused` 保留，未部署、重启、恢复账号或调用线上模型。

## 证据与时间

对 `D:/DSHData/sessions/--D-Code-Projects-FatFishLife-data-dsh-qq-work--` 下 17 份 `session.v4.jsonl.zstd` 只读解压，以 `tool/call.data.callId` 与 `tool/result.data.message.toolCallId` 配对、去重。仅输出工具名、计数、时间聚合，不导出正文、身份、参数或凭据。以下均为北京时间：

| 项目 | 结果 |
| --- | --- |
| 唯一 `compress` 调用 | 96 次，全部找到结果 |
| 结果报错且包含 `Tool is outside this social capability set` | 95 次 |
| 拒绝调用时间 | 11 月 5 日 18:19:22.127—18:29:05.733 |
| 拒绝结果时间 | 18:19:22.138—18:29:05.765 |
| 源码修复提交 | `c7b1282`，18:28:16；提交后仍有 12 次历史拒绝 |
| 首个非错误结果 | 调用 18:30:11.171，结果 18:30:11.480 |

源码提交时间不能当作进程生效时间；最后一条拒绝晚于提交并不证明当前文件仍有缺陷。上述归档没有证明每条消息都已送达 QQ，也不能证明一次非错误工具结果一定进行了模型摘要。

## 当前验证

- 新增 `policy.test.mjs` 用例经过实际 `installSocialScope → FatFishPolicy.toolDenial` 路径：四个工具在群和普通私聊均放行，放行时不发报卡点通知；跨会话目标、全局静默和账号暂停仍拒绝。
- 源码与已安装副本分别执行 8 条隔离 mock 检查，均通过；不执行工具、不调用模型、不访问网络。
- 单独的上下文用例通过；完整 `policy.test.mjs` 共 35 项通过、0 失败。测试子进程使用随机生成且不存在的标记路径隔离生产暂停状态，实际暂停标记未删除。

## 原生能力与后续边界

读取实际 `D:/dsh/resources/app.asar` 内官方包，`dsh-agent`、`dsh-compaction-basic`、`dsh-sdk-app` 均为 `0.2.2-rc.1`。`dsh-compaction-basic/lib/index.js` 确有 `compactIfNeeded` 的压力/溢出路径，以及 `compactNow(agent, signal, sourceCommandId)`；后者通过 `agent.runMaintenance` 申请空闲维护，忙碌时拒绝，并在摘要写入后完成持久化。包中有此能力不等于当前 preset 已启用或线上已触发。

官方当前[压缩文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/compaction.zh.md)与[原生压缩包说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/compaction-basic/README.md)由 Context7 查询核对；文档 master 与本机版本分别取证，不混称同一版本。原生摘要会增加模型请求；`compactNow` 也不是旧 `compress` 工具的同名替代接口。

已安装 327 个官方主 bundle 和 `dsh-context 0.78.0` 主入口均未检出 `selfNote` / `self_note`。目前不能据此承诺已有可直接调用的 selfNote API，也不另造并行记忆库。

后续最小路径：

1. 保持账号暂停，先从已有请求计量记录聚合每会话的输入 token、系统/工具前缀占比、工具失败与压缩次数；不读出正文。核实当前 preset 实际挂载的原生压缩组件。
2. 如原生压力压缩已满足需求，直接复用。只有测量确认存在空闲后下一轮压力，才通过已有维护入口对空闲会话调用 `compactNow`；遵循其排队、取消与持久化机制，不新增另一套定时器或摘要引擎。
3. selfNote 必须先确认当前版本真实接口、归属和持久化语义，再决定是否复用。长期偏好继续用现有记忆入口，避免把聊天压缩摘要自动当作长期事实。
4. 先比较压缩前后 token、摘要请求成本和失败率，再决定预算；本轮不把上下文预算提高到 300k，不改生产配置或恢复真实账号。
