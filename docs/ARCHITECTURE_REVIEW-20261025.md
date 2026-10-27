# Letta / Mem0 思路的本地记忆架构审查

2026-10-27 最新进展：原7项均已完成源码修复和针对性验证。此前FTS、表达/候选输出隔离、来源幂等、人工审核优先已加载；本轮补齐逐短语风格写入/旧批次拆分，以及同平台/完整UMO/public/verified长期候选进入普通聊天。候选归属从可证实来源持久化，跨平台去重隔离，原文过期仍召回，缺失来源不猜测，人工拒绝优先。完整640项回归通过（1跳过），随后新增普通聊天钩子测试的24项插件专项通过；生产停服备份迁移并完整重启，28条候选原内容/审核字段不变，27条可归属、11条verified，只读召回通过。真实入站效果仍待日常观察；详见handoff本日条目。下方表格及待重载描述保留当时审查证据，不代表最新运行状态。

审查 `64f25b5`、`760976d` 及后续准入修订，代码快照对应 `142c81d`。本轮只审查，未修改记忆实现。复现使用临时SQLite库和模拟事件；生产库只做数量/结构只读核对，不导出聊天正文。

2026-10-25 后续修复：下表第1项FTS事务锁已修。审核状态、索引删除和新增使用同一个SQLite连接及事务；重复通过只保留一条索引，拒绝或退回待审同时移除索引，索引写入失败会回滚审核。QQ审核命令改用已有 `asyncio.to_thread`，失败明确返回未保存，不阻塞事件循环或假报通过。原有候选索引可通过 `MemoryStore.rebuild_candidate_index()` 按verified状态原子重建，不修改候选正文、命中数或审核记录。其余6项仍待修复，以下表格保留原始审查证据。

2026-10-26 源码修复（生产待重载memory插件）：表达检索现在必须传平台和完整UMO，self_learning仅接受能直接核对的完整QQ群UMO，旧裸群号不猜测适配器。共享style按platform/session/public在SQL中先过滤再limit，未绑定的旧全局表达不再自动注入。统计改为只读聚合计数，不通过全局正文检索取得。全局候选列表及审核仅允许已认证老大私聊，群中即使是老大也不查询/操作候选。其余长期召回、来源幂等、人工拒绝优先级、批次风格4项仍未修。本节不是生产验收：运行后端进程身份路径不可读，电脑控制因无法可靠识别当前浏览器URL被安全检查停止，未强杀或绕过认证。

## 当前实现

2026-10-26 晚源码修复（待完整重启）：来源事件ID唯一账本与候选同事务写入，游标持久化/单调推进，故重扫、失败重试及多实例并发不能叠加同一条证据。晋升依原事件日期和不同事件数，旧hits不作为充分依据；自动审核只更新candidate状态，保留人工rejected/verified和审核备注。完整627项测试通过；原生插件重载不清理fatfish_core共享模块缓存，生产尚未应用此单元。剩余普通聊天长期召回与批次短语粒度2项待修，原表保留历史证据。

目前没有实际引入 Letta/Mem0 SDK或服务，而是借鉴其思路，在现有AstrBot记忆插件内增加SQLite块、规则准入、候选审核、FTS5和相关表达注入。准入和表达打分都是本地规则，没有新增逐条LLM分析。

方向能保留现有轻量部署，但几个关键消费链尚未闭环。现有测试通过不能证明这些新能力已经有效。

## 可复现问题

| 等级 | 问题 | 位置 | 证据与影响 |
|---|---|---|---|
| P1 | 审核在未提交UPDATE事务内另开写连接更新FTS，吞掉锁异常 | `fatfish_core/memory.py:228`、`:242`、`:256` | 审核返回true、状态verified，但等待10.97秒、FTS仍0行。生产库只读快照也是5条verified、0条FTS，查询依赖LIKE兜底；同步审批命令还会阻塞事件循环 |
| P1 | 表达检索未传会话，读取所有群的expression_patterns和所有scope/session的style事件 | `bots/astrbot_plugin_fatfish_memory/main.py:137`、`style.py:69`、`:93` | GroupA表达可进入GroupB的system_prompt，与同群学习、完整会话隔离约定冲突 |
| P1 | 全局候选列表只检查owner，不检查私聊或候选所属会话 | `bots/astrbot_plugin_fatfish_memory/main.py:419` | GroupA公开消息正常进入候选后，老大在GroupB调用 `/memory pending` 能看到GroupA内容。查看权限不能替代发送目标的隐私边界 |
| P1 | 已审核候选没有接入普通聊天检索 | `fatfish_core/context.py:57` | `store.search`能命中verified候选，`build_context`只读最近events；原文退出最近窗口或被清理后，长期候选不参与普通聊天，仅命令搜索可用 |
| P2 | 游标仅在内存，重启从0重扫；命中数没有来源事件去重 | `bots/astrbot_plugin_fatfish_memory/main.py:322`、`fatfish_core/memory.py:209`、`fatfish_core/extract.py:83` | 一条原消息重扫3次即hits=3；模拟自然跨日条件后自动晋升，旧消息重放被当成新证据 |
| P2 | 自动偏好准入覆盖人工rejected | `fatfish_core/extract.py:63`、`:71` | 人工拒绝候选后，再扫原事件就重新变为verified |
| P2 | 写入按批次拼接，读取把总长超过30字的批次整条丢弃 | `fatfish_core/learning.py:50`、`bots/astrbot_plugin_fatfish_memory/style.py:141` | 正常保存10个四字短语，返回saved=10、数据库1行，但精确命中其中短语的查询仍得到空表达块 |

当前候选自动提取只扫public，风格正常写入也以public为主。以上证明跨群路径可复现，**没有证明生产私聊正文已经泄露**。直接插入private候选/style的模拟旁路不能冒充生产事故。

## 只读块的实际边界

生产共享库确有 `persona` 块，1471字符、read_only=true；但当前插件不从块读取运行人设。`get_block/set_block`的唯一业务调用者是 `scripts/persona_guard.py`，当前FatFish启动/守护计划任务也未调用它。它现在是可手工恢复的旁路基线，还不是运行链中的只读约束。

[Letta文档](https://docs.letta.com/v1-sdk/memory/memory-blocks)的read_only约束agent记忆工具修改同一个块；给平行副本加标记不能保护另一张表。[Mem0作用域设计](https://github.com/mem0ai/mem0/blob/main/docs/platform/features/entity-scoped-memory.mdx)将身份/会话过滤放在检索本身，本地实现也应在每条检索和输出入口强制过滤。

## 建议顺序

1. 先修会话过滤、候选输出边界及FTS事务。审核状态与索引增删放在同一事务，别吞错。
2. 持久化游标，按来源event_id幂等；保留人工审核决定。来源事件标识不必重新引入发送人字段。
3. 将同会话已审核候选接入普通聊天检索，统一短语存取粒度；验证原文超窗/清理后的长期召回。
4. 明确人设唯一来源；跨群全局风格需要独立的公开审核状态，不能自动等同于原始群语料。

先完成当前闭环，再决定是否接入实际框架；目前不建议并联两套记忆服务或恢复逐条模型提取。

## 验证限制

证据在忽略目录 `outputs/architecture-review-20261025/`：`admission-results.json`、`pending-cross-group-repro.json`、`integration-repro.json`、`style-batch-repro.json`及复现脚本。跨日重扫使用临时库模拟日期；后续独立行为复现跳过已单独证明的FTS锁等待，未改变待测晋升或审核逻辑。

Open Code Review CLI自动检查因总token预算上限停止，4个目标文件没有完成审查，不能把0评论视为通过。以上结论依据源码核查、并行独立审查、临时库执行和生产库只读聚合，不依赖该失败结果。
