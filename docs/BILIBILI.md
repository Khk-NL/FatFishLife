# 成片投稿适配器

`fatfish_bili` 复用 bili-agent 0.6.0 的 `upload video` 和 `upload status`，不读取或复制登录凭据。参数已与本机命令帮助和安装源码核对；Context7 尚未收录该工具。

## 默认生成本地草稿

先渲染成片，保留同名 `.result.json` 报告及 `.cover.jpg` 封面。适配器要求报告版本为 1、状态为 `completed`，视频、封面和报告自身路径一致，媒体文件存在且非空。它复用渲染器的成功检查，不重新编码或声称重新验证媒体内容。

准备投稿元数据 JSON：

```json
{
  "title": "经确认的投稿标题",
  "description": "经确认的简介",
  "tags": ["经确认的标签"],
  "zone": 0,
  "tid": 0,
  "ai_declare": true,
  "private": false
}
```

`zone` 和 `tid` 的 0 是占位值，工具会拒绝；请填写账号投稿页确认的新版分区和旧版分区 ID。也可自行运行 `bili upload zones` 查询新版分区（需要账号连接）。两个分区均需明确提供，避免 bili-cli 根据标题联网猜测。标题 1～80 字，简介最多 2000 字，标签 1～10 个。

```powershell
python -m fatfish_bili publish outputs/my-video.mp4 --meta publish-meta.json
```

这一步不启动 bili-cli，也不登录、上传或访问网络；写入 `my-video.publish-draft.json`，包含媒体路径、渲染报告、完整元数据及实际命令参数。即使没有安装 bili-cli 也能制作草稿。

## 明确确认后提交

核对草稿与成片后，在同一命令增加 `--confirm`，并指向已登录的 bili-cli 环境：

```powershell
python -m fatfish_bili publish outputs/my-video.mp4 --meta publish-meta.json --confirm --bili D:/Code/Apps/bili-venv/Scripts/bili.exe --bili-home D:/Code/Apps/bili-home
```

`--bili-home` 需替换为已有登录环境，不要把凭据写进元数据。Python 对应入口：

```python
from fatfish_bili import PublishMeta, publish

meta = PublishMeta.from_dict(metadata)
draft = publish(video_path, meta)  # 本地草稿
result = publish(video_path, meta, dry_run=False, bili_exe=bili_path, bili_home=profile_path)
```

只有 bili-cli 成功返回 BV 号，结果才标为 `submitted` 并保存 `.publish-draft.result.json` 回执；这表示已经提交审核，不能据此认定公开发布。CLI 或认证错误直接失败，不自动重试。超时可能无法确认远端是否已收到投稿，应先检查稿件再决定是否重试。

```powershell
python -m fatfish_bili status BVxxxxxxxxxx --bili D:/Code/Apps/bili-venv/Scripts/bili.exe --bili-home D:/Code/Apps/bili-home
```

本地草稿会按本次元数据重写；回执单独保存。适配器没有后台任务或自动重复投稿。真实上传、账号分区、风控及审核状态仍需人工账号验收，本项目测试不会实际投稿。
