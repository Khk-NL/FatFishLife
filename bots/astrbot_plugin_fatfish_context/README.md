# 会话整理和成本记录

在模型请求前整理当前会话的媒体历史，保留最近一轮中的一张图片、历史文字和工具调用配对。旧插件误写成字符串的图片编码会被移除，文字说明保留。单次最多处理两张新图片，超出时提示分次发送。整理过程不调用模型。

老大在 QQ 私聊发送 `/成本`，查看已记录的近 24 小时调用数、缓存比例和估算费用。插件每小时写入本地 `plugin_data/astrbot_plugin_fatfish_context/cost-latest.json`，不会为报告发送主动消息。价格和统计边界见 `docs/COST_MONITORING.md`。

每群、每私聊沿用 AstrBot 原生会话。压缩策略和本地 MiniCPM 提供商由 `scripts/configure_cost_policy.py` 配置，本插件不另建共享聊天历史。群聊额度由现有 token_controller 执行。
