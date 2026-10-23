# 表情图描述生成提示词

给视觉模型用。目标是让 `meme_manager` 的语义检索能用上这些表情。

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

## 输出汇总格式

把每张图的结果拼成下面这个结构，存为资源包里的 `semantic_metadata.json`：

```json
{
  "schema_version": 1,
  "images": {
    "能天使/web-exusiai-09_乖巧.jpg": {
      "caption": "能天使双手合十歪头微笑，眼睛亮亮的，看起来在撒娇",
      "tags": ["乖巧", "撒娇", "能天使", "开心"],
      "caption_status": "done"
    }
  }
}
```

key 必须是 `分类/文件名`，和 `memes/` 下的相对路径一致，否则插件对不上。

## 合并脚本

模型按每张图输出一行 JSON 的话，用下面这段合并（把 `results.jsonl` 换成你的输出文件，每行带 `path` 字段）：

```python
import json, pathlib
rows = [json.loads(line) for line in pathlib.Path("results.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
images = {
    row["path"]: {
        "caption": row["caption"],
        "tags": row["tags"],
        "caption_status": "done",
    }
    for row in rows
}
pathlib.Path("semantic_metadata.json").write_text(
    json.dumps({"schema_version": 1, "images": images}, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
```

放到 `D:\Code\Apps\AstrBot\data\plugin_data\meme_manager\packs\builtin-default\semantic_metadata.json`，重启 AstrBot，插件会自动建索引。

## 已生成的粗描述

当前这份 `semantic_metadata.json` 是用文件名关键词填的（96 张），插件判定「描述未完成」，没有建索引。用上面的提示词重新生成一遍覆盖掉即可。
