# Letta / Mem0 思路的本地记忆架构审查

审查 `64f25b5`、`760976d` 及后续准入修订，代码快照对应 `142c81d`。本轮只审查，未修改记忆实现。复现使用临时SQLite库和模拟事件；生产库只做数量/结构只读核对，不导出聊天正文。

2026-10-25 后续修复：下表第1项FTS事务锁已修。审核状态、索引删除和新增使用同一个SQLite连接及事务；重复通过只保留一条索引，拒绝或退回待审同时移除索引，索引写入失败会回滚审核。QQ审核命令改用已有 `asyncio.to_thread`，失败明确返回未保存，不阻塞事件循环或假报通过。原有候选索引可通过 `MemoryStore.rebuild_candidate_index()` 按verified状态原子重建，不修改候选正文、命中数或审核记录。其余6项仍待修复，以下表格保留原始审查证据。

## 当前实现

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
