# astrbot_plugin_fatfish_lore

苹果乐的设定库。常驻人设只保留人格、语气和边界；世界观、人物关系、经历、对话示例放在完整角色卡里，按需检索。

## 为什么不用内置知识库

AstrBot 内置知识库必须绑定 embedding 模型。当前只配了 DeepSeek 对话模型，没有 embedding，所以这里用 2-gram 关键词检索，零依赖、离线可用。

以后配置了 embedding（SiliconFlow BGE、OpenAI embeddings 等），可以把 `docs/persona/apple-le-full.md` 导入内置知识库，再把 `lore_lookup` 换成内置检索。

## 配置

- `lore_path`：完整角色卡路径，默认 `D:/Code/Projects/FatFishLife/docs/persona/apple-le-full.md`
- `max_chars`：单次返回上限，默认 1800

## 用法

```
/设定 目录
/设定 德克萨斯
/设定 莫斯提马 往事
```

LLM 工具：`lore_lookup(topic)`。人设里已提示「需要时查设定库」，模型会在问到世界观细节时调用。

## 维护

改 `apple-le-full.md` 后，`/设定` 会自动读取最新内容（每次检索前不缓存），但章节索引在插件启动时构建，改完章节结构需要重载插件。

常驻人设在 `docs/persona/apple-le-core.md`，改完要写回 AstrBot 的人设库（`data/data_v4.db` 的 `personas` 表，`persona_id='apple-le'`）。
