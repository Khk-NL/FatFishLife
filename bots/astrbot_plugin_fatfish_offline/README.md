# astrbot_plugin_fatfish_offline

配置时段内不调用任何云端大模型，改用本地规则回复。人设和角色卡不受影响。

## 工作方式

1. 每条消息先经过本插件。非离线时段直接放行，原聊天流程不变。
2. 离线时段：`event.stop_event()` 在网络请求前拦截，普通聊天不会产生任何 API 调用。
3. 被 @、点名、私聊或连续追问时，按意图从台词库挑一句回复；无人叫它时保持沉默。
4. 恢复时间由配置动态计算，台词里只有 `{resume}` 占位符。
5. 状态写入 `data/plugin_data/astrbot_plugin_fatfish_offline/offline.json`，B 站自动回复插件会读取它，离线时同样不发模型请求。

戳头像使用 NapCat 的原始 `notify/poke` 或 `Poke` 组件识别目标，只响应戳到机器人本人的事件。在线时进入独立的戳一戳对话触发，离线时用本地戳一戳台词。只发一个空 @ 会得到简短本地回应；@ 加文字或图片继续普通对话，不会当成戳一戳。群聊和私聊均适用。

## 配置

| 项 | 说明 |
| --- | --- |
| `enabled` | 总开关 |
| `windows` | 时段，默认 `08:00-12:00`、`14:00-18:00` |
| `weekdays` | 工作日，默认周一到周五 |
| `holidays` | 法定节假日例外（YYYY-MM-DD） |
| `workdays` | 调休补班（YYYY-MM-DD） |
| `reason` | 离线原因，决定台词库 |
| `group_cooldown` / `user_cooldown` / `max_per_hour` | 节流 |
| `context_ttl` | 短期上下文有效期 |
| `owner_qq` | 主人 QQ，可用命令切换模式 |

## 命令

```
/离线 状态
/离线 开
/离线 关
/离线 自动
```

`开/关` 是手动覆盖，优先级高于时段判断；`自动` 清除覆盖。

## 台词

`templates.py` 按原因和意图分组，支持 `{name}`、`{resume}`，带近期去重。改台词不需要动逻辑。

## 测试

```powershell
python -m unittest tests.test_offline_logic -v
```

覆盖时段边界、周末/节假日/调休、恢复时间文案、意图识别、节流和上下文过期。
