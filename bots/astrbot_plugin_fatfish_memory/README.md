# astrbot_plugin_fatfish_memory

大肥鱼双平台共享记忆插件。QQ（NapCat/OneBot v11）与 B 站适配器读写同一个 SQLite 库：

- 人设：一套人设，两边共用
- 主人资料：按平台 UID 识别，非主人看不到私人记忆
- 聊天摘要：消息截断后写入，默认保留 90 天
- 事件与每日总结：主人可导入、检索

## 数据

默认数据库：`AstrBot/data/plugin_data/astrbot_plugin_fatfish_memory/memory.db`（WAL 模式）。

`private` 行只返回给主人；`public` 行可用于选题、文案和公开回复。

## 命令

```
/记忆 搜索 <关键词>
/记忆 最近
/记忆 状态
/记忆 记住 <内容>     仅主人
/记忆 公开 <内容>     仅主人
/记忆 人设 [内容]     仅主人可改
/记忆 导入 <总结>     仅主人
/记忆 总结            仅主人
/记忆 绑定 <B站UID>   仅主人
```

LLM 工具：`memory_recall`、`memory_remember`。

## 配置

`owner_ids` 写成 `qq:123456,bilibili:654321`。也可以在聊天里用 `/记忆 绑定` 补充 B 站 UID。
