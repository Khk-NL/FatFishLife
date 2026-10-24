# 成本自检

自检直接读取 AstrBot 的 `provider_stats`，不调用模型或外部服务，不读取对话内容，也不输出会话 ID。报告按小时、模型和调用用途聚合真实的输入未缓存、输入缓存、输出计数。

媒体历史整理、老大私聊 `/成本` 和小时报告现在由已有的 `fatfish_memory` 提供，复用 `fatfish_core.context_policy` 与 `fatfish_core.costs`。独立的 `fatfish_context` 插件已移除，不需要再安装一个插件。报告仍写入原来的 `data/plugin_data/astrbot_plugin_fatfish_context/cost-latest.json`，只是保留已有文件位置。

```powershell
python scripts/cost_report.py --db D:/Code/Apps/AstrBot/data/data_v4.db --hours 1
python scripts/cost_report.py --db D:/Code/Apps/AstrBot/data/data_v4.db --today --output outputs/cost/daily.json
python scripts/cost_report.py --db D:/Code/Apps/AstrBot/data/data_v4.db --day 2026-10-24 --json
```

本地模型须用 `--local-provider <实际提供商ID>` 明确指定，可重复传入。仅模型名字像 MiniCPM 或 Qwen 不足以判断请求在本机执行。报告将明确指定的本地调用 API 费用记为 0，本机耗电和资源占用不在 API 费用中。

## 看什么

- 每小时的调用数、未缓存输入和输出。先定位调用频率或单次上下文膨胀，再决定调整哪些功能。
- 缓存命中率按 `cached / (cached + uncached)` 计算，不将输出混入分母。先保持人设、规则和工具说明的稳定前缀，将时间、会话摘要和检索结果放到动态部分。
- `by_model` 中的用途和模型。后台分析应单独记账，少量回复不等于少量后台调用。
- 每天保存一份 JSON，对比配置调整前后。`--warning-cny` 默认 5 元，仅产生报告提醒，不自动改配置或禁用功能；可以由维护任务读取 `alerts`。

## 估算边界

费率核对日期为 2026-10-24，来源为 [DeepSeek 官方价格页](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)。单位是每百万 tokens：

| 模型 | 未缓存输入（闲时～高峰） | 缓存输入 | 输出 |
| --- | --- | --- | --- |
| deepseek-flash | ¥1～2 | ¥0.02～0.04 | ¥4～8 |
| deepseek-v4-pro | ¥4.5～9 | ¥0.15～0.30 | ¥13.5～27 |

报告对实际记录的 tokens 使用峰谷价格区间，不猜测法定节假日和账户计费时段。它不是账单、账户余额或完整费用承诺。价格变化后应更新费率与核对日期。

未知模型会显示未定价，`estimate_cny` 为 `null`；计数缺失也会标记不完整。`known_cost_cny_low/high` 只代表已识别部分，不能当总额。没有表、没有记录或未接入统计的调用都不能当作账户零消费。

HTTP 请求成功、插件显示已开启、每日预算配置存在，都不能单独证明计量覆盖完整。直接调用模型的插件必须写回用量；图像、语音、搜索和付费生成若没有对应计数，仍须核对服务商账单。

## 当前部署策略

- 原生会话按完整 UMO 隔离；同群成员共用该群上下文，私聊彼此独立。本地 MiniCPM5-2B 压缩达到阈值的旧记录，保留最近轮次，中文摘要最多 250 字。
- 关闭 Self Learning 的逐条好感度、云端高频分析和人设演化注入；群语料由现有 style 插件积累后批量交本地模型审核。图谱提取也指定本地模型，失效时报告错误，不回退到云模型。
- 常驻核心约 688 字，完整参考留在归档和设定库。称呼依据、记忆、图谱证据放在当前用户消息的动态部分，人设与规则前缀保持稳定。
- DeepSeek 关闭默认思考；最多 12 轮上下文、6 次工具步骤和 1 次请求尝试。图片缩到 768 边长，当前图片最多 2 张，历史仅保留最近一轮 1 张。
- 现有 token_controller 已覆盖统计中发现的 7 个群，每群每天 50 万 tokens，达到上限停止模型调用。新群须在控制台加入列表。这是 token 额度，不是全账户每天 5 元的承诺。

本地服务只监听回环地址，并使用本地密钥。安装：`python scripts/setup_minicpm_context.py --root D:/Code/Apps/MiniCPM`；停 AstrBot 后运行 `python scripts/configure_cost_policy.py --astrbot D:/Code/Apps/AstrBot --model-root D:/Code/Apps/MiniCPM --apply`，再由现有 watchdog 启动两项服务。该脚本备份配置且不显示密钥。

历史修复先用 `scripts/repair_chat_history.py` 预览，指定 `--apply` 时逐会话备份原文再更新。不会合并会话，也不需要伪装成主人发送 `/reset`。

## 旧 context 配置迁移

先停 AstrBot，在首次加载合并后的记忆插件前运行：

```powershell
python scripts/merge_context_config.py --data-dir D:/Code/Apps/AstrBot/data
python scripts/merge_context_config.py --data-dir D:/Code/Apps/AstrBot/data --apply
```

第一条只预览；第二条备份旧记忆配置后，将缺失字段补进 `astrbot_plugin_fatfish_memory_config.json`。已存在的记忆配置字段优先保留，不覆盖手动修改。

| 旧 `fatfish_context` 字段 | 合并后 `fatfish_memory` 字段 |
| --- | --- |
| `enabled` | `context_hygiene_enabled` |
| `image_history_turns` | 同名，默认 1 |
| `max_current_images` | 同名，默认 2 |
| `monitor_interval_seconds` | 同名，默认 3600 秒 |
| `cost_warning_cny` | 同名，默认 5 |
| 原先始终运行的统计任务 | `cost_monitor_enabled`，默认 true |

重启前停用或移走本机旧 `astrbot_plugin_fatfish_context` 插件目录，保留旧报告数据即可。新的统计任务随记忆插件卸载取消，避免重复计时器；媒体整理仍使用原来的请求钩子优先级 -500。
