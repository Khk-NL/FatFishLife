# 表情图描述生成提示词

给视觉模型用。目标是让 `meme_manager` 的语义检索能用上这些表情。

当前安装的插件使用 `schema_version: "2.0"` 和内容、分类、路径共同生成的记录 ID。下面的简短提示词可用于人工查看单图；批量生成请使用后面的脚本，它直接复用插件的当前提示词、GIF 抽帧、校验和索引实现。

## System prompt

```
你是表情包标注助手。看用户给的图片，输出画面描述和标签，供中文语义检索使用。

规则：
- caption：20-40 字，写清楚主体、角色、动作、表情、画面文字；看不清就描述外观，不要编造角色或剧情。
- tags：3-6 个短词，覆盖情绪、动作、主题、角色名，例如：开心、摸鱼、无语、能天使、苹果。
- 角色判断：明日方舟的能天使、苹果乐、莫斯提马、菲亚梅塔、蕾缪安、送葬人等可以直接用名字；不确定就写外观特征，比如「蓝发天使」「红发少女」。
- 不要输出 Markdown，不要解释，只输出一行 JSON：
{"caption": "...", "tags": ["...", "..."]}
```

## 每张图的输入

```
文件名：web-exusiai-09_乖巧.jpg
分类：能天使
原始关键词：乖巧
```

把这三行连同图片一起发给模型。文件名里的关键词能减少幻觉，但不要让模型照抄关键词当 caption。

## 自动生成与索引

在项目目录用 AstrBot 自己的 Python 环境执行。脚本从 AstrBot 已保存的 Provider 配置读取凭据，使用 DeepSeek Flash 看图、BGE-M3 建向量；凭据不进入输出文件。

```powershell
& 'D:\Code\Apps\AstrBot\.venv\Scripts\python.exe' scripts/generate_meme_semantics.py `
  --astrbot-root 'D:\Code\Apps\AstrBot' `
  --output-dir 'D:\Code\Codex\2026-10-22\new-chat\outputs\meme-semantics' `
  --limit 3 --skip-index
```

首批成功后，去掉 `--limit 3 --skip-index` 再执行即可处理剩余图片并建索引。默认并发为 4，可用 `--concurrency` 调整。执行期间不要同时从插件控制台开始语义队列。

每张成功后都会原子保存，重新执行时跳过已有完整描述和人工覆盖内容；失败项会记录异常类型，后续执行只补齐缺失项。脚本会保留分类目录和图片文件，模型提出的分类疑问写入 `needs_review`，供控制台查看。

结果保存在资源包的 `semantic_metadata.json`；输出目录的 `semantic-result.json` 提供处理数量、失败数量、分类复核数量及 `index_ready`。只有所有图片描述完整时才开始建立索引。旧版以 `分类/文件名` 作为 key 的 schema 1 文件需要先用 `scripts/migrate_meme_metadata.py` 迁移，不能直接拼接覆盖当前文件。
