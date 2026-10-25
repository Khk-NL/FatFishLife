# 主动搭话与关键词概率

数字由用户自行填写；本次保留原基础概率、启用范围、群静音、离线/节能、冷却和每小时上限，不自动打开原先关闭的群插话。全部概率以0～1表示，0.1就是10%。公式为 `min(max, p0 + n × step)`。

## 群内随机主动插话

AstrBot的 `fatfish_offline` WebUI配置：

| 字段 | 原值/新增默认 | 含义 |
|---|---|---|
| ambient_chance | 保留现有值，schema默认0.025 | p0 |
| ambient_probability_step | 0 | 每次合格机会未成功发送后的增量 |
| ambient_probability_max | 1 | 概率上限 |
| ambient_cooldown | 保留现有值，默认300秒 | 抽中时先预约，实际成功后刷新起点 |
| ambient_hourly_limit | 保留现有值，默认3 | 每群每小时发起插话的请求上限，抽中即预占；0保持关闭 |

`n`只统计已满足活跃度、普通文字、冷却和小时额度等条件的群消息。@、唤醒、引用、续聊依旧按原入口应答，不参与随机概率；不满足门禁的消息不累计。概率命中但生成/发送失败仍算未发送，只有成功发出对应随机回复才清零。抽中时就先预约冷却和小时额度，生成失败也不退还，避免生成期间同会话多条命中造成排队和重复费用；成功发送只刷新冷却起点，不重复扣小时额度。旧按小时衰减已由这个线性公式取代，`GroupConfig.decay_factor`仅作为旧调用兼容参数保留。

## 关键词搭话

同一 `fatfish_offline` 配置新增：`keyword_probability`（p0，默认1，保留原来命中即触发的行为）、`keyword_probability_step`（默认0）、`keyword_probability_max`（默认1）、`keyword_cooldown`（默认90秒）。

只在非@/非明确唤醒、非续聊且命中既有关键词时抽签。两个计数通道分别按完整UMO维护，例如不同适配器的同号群互不影响，随机插话成功不会清掉关键词计数。关键词抽中立即预约冷却，实际回复成功后才把n清零并刷新冷却起点；生成或发送失败保留n和已经预约的冷却，冷却中的消息不累计。

## 私聊定时主动消息

沿用社区 [Proactive Chat v1.2.6](https://github.com/Pancakes-Labs/astrbot_plugin_proactive_chat)（AGPL-3.0）的现成调度、会话白名单、免打扰、未回复次数限制与发送器，不增加定时器。安装薄适配前停止AstrBot：

```powershell
python scripts/configure_proactive_probability.py --astrbot D:/Code/Apps/AstrBot --apply
```

默认只预览；实际应用先备份并读回，保留上游许可证及原会话名单/间隔。源版本或调用形态不符时停止，不能盲目覆盖升级后的社区插件。

原插件WebUI的 `friend_settings.probability_settings`（私聊）和 `group_settings.probability_settings`（其原有群定时主动功能）都提供 `base`、`step`、`max`。默认分别为1、0、1，维持原先每次合格定时机会都执行的行为。原来关闭的群定时功能不因此开启。原插件的逐会话配置覆写同样允许 `probability_settings`。

这里的 `n`按每个完整会话的**合格定时机会**计算，不按普通收到的聊天消息数计算。未抽中时直接走原重调度，不调用模型；生成失败或发送失败不清零；只有原发送器确认成功才复位。节能状态复用现有FatFish离线信号，离线、免打扰、未启用、未配置或未回复次数达到上限时不累计。手动主动触发保留现有显式操作行为，但不能绕过节能状态。

这些计数只保存在进程内且有数量上限，不保存聊天正文或发送人；插件重载后n归零。它们与表情、语音计数独立。
