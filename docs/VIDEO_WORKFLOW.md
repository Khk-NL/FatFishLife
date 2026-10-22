# 从话题生成视频

单入口已经包含分镜、配置校验、角色拼贴和实际渲染：

```powershell
python -m fatfish_story create --topic "新版本角色讨论" --provider mock --out outputs/generated/demo.json
```

默认生成 30 秒、1920×1080、30fps 的 MP4，同时返回配置路径和渲染报告中的 `video`、`cover`、`subtitles`、`report`。命令退出码为 0 且输出 `stage: video` 才表示本次生成视频完成；`--no-render` 只完成分镜，输出 `stage: storyboard`。

`mock` 用固定测试文案跑通本地流程，不调用模型。正式文案省略 `--provider mock`，使用已配置的 `DEEPSEEK_API_KEY`；鉴权或网络失败直接报错，非法 JSON 或不符合引擎要求的分镜最多重试一次。模型生成的配置必须经过视频引擎校验。

## 模板和素材

```powershell
python -m fatfish_story create --topic "双人聊新版本" --template dialogue --character 1006 --character 1005 --provider mock --out outputs/generated/dialogue.json
python -m fatfish_story create --topic "资讯截图解读" --template news --panel assets/originals/reference-layout.png --provider mock --out outputs/generated/news.json
```

自动拼贴目前仅开放已校准的正面模型：`1006` 银狼、`1005` 卡芙卡、`1205` 刃、`1224` 仙舟三月七。未校准角色会明确报错，不会静默使用立绘冒充正脸。指定角色会覆盖模型选角。

脸部固定来自 `assets/originals/kobe-original.png`，使用 Web 版已经验收的 `assets/web/kobe-face.json` 取脸范围，排除身体，再复用正面模型的底图和头发层。脸部最后合成，保留比例，避免头发覆盖五官。生成的透明 PNG 保存到配置旁的 `.assets/` 文件夹，原图不会修改。

自动拼贴只需现有 FFmpeg，不额外安装图像处理依赖。音乐默认使用项目的原创合成测试音轨，正式投稿前需检查画面、字幕和音乐。

## 覆盖和失败

配置、分镜元数据和视频默认拒绝覆盖；确需替换时加 `--overwrite`。替换配置前先通过引擎校验，生成失败时保留原配置和元数据。分镜元数据中的 `stage: storyboard` 只证明分镜完成；视频发布应使用渲染生成的 `.result.json`，不能使用 `.meta.json` 判断视频完成。

三份传统模板示例 `examples/single.json`、`dialogue.json`、`news.json` 均为 30 秒。`scripts/make_examples.py` 重新生成时也保持这一时长。
