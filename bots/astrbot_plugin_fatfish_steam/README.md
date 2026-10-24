# Steam 公开价格

通过 Steam 商店公开搜索和 `appdetails` 按需查询当前区域价格，不需要 Steam Web API Key，不下载全量游戏目录，不启动后台监控，也不改变原 SteamSaleTracker 的监控状态。

`/steam 620`、`/steam Portal 2`、`/steam 价格 620` 或 `/steam <商店app链接>` 均可查询。名称存在歧义时返回最多5个候选，选 appid 后再查，避免把第一条误认成目标。LLM 可调用 `fatfish_steam_price(query)`。

`country` 默认 `cn`；`proxy` 留空直连，需要代理时可填写现有 HTTP 代理（如 `http://127.0.0.1:7890`）。公开商店接口受平台和网络状态影响，失败会明确报告；缺少价格不当作免费，只有 `is_free=true` 才显示免费游玩。价格以返回的查询时点和区域为准。

查询成功或失败只向共享记忆写入固定的私人 `steam/search` 能力经历，进入每日反思及 `/生活 成长`。查询词、账号、代理凭据和商店响应正文不写入成长记录。

旧 SteamSaleTracker 的全量目录更新依赖其自身配置和服务权限，缺少旧目录的 Key 不影响这个公开价格查询入口；保留旧插件不代表旧目录下载或监控已经修复。
