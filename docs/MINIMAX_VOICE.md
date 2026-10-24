# MiniMax 音色参考与现有语音路由

继续使用已安装的 `tts_emotion_router` 合成与路由，不新增语音插件。参考处理沿用项目现有 FFmpeg，短句识别沿用 AstrBot 已配置的 STT 适配器。

## 两种上传用途

| 用途 | 要求 | 作用 |
|---|---|---|
| `voice_clone` | 10 秒～5 分钟，mp3/m4a/wav，不超过 20 MB | 必需的音色参考，上传后取得 `file_id` |
| `prompt_audio` | 小于 8 秒，同样不超过 20 MB | 可选示例；通过 `clone_prompt.prompt_audio` 和对应 `prompt_text` 一起提交 |

两者都调用 `POST /v1/files/upload`，通过 `purpose` 区分，然后调用 `POST /v1/voice_clone`。可选短句不能代替长参考。来源：[上传复刻音频](https://platform.minimax.cn/docs/api-reference/voice-cloning-uploadcloneaudio)、[上传示例音频](https://platform.minimax.cn/docs/api-reference/voice-cloning-uploadprompt)、[音色复刻](https://platform.minimax.cn/docs/api-reference/voice-cloning-clone)。

## 本机已准备的参考

从用户提供的原版能天使中配合集截取了 45 秒长参考，以及一个完整短句；音频及其转写保存在忽略目录 `outputs/minimax-reference-20261025/`。原始文件不改动。两个新约语音合集均超过 5 分钟，不能未经截取就整份作为长参考提交。

预览参数与文件校验，不联网上传：

```powershell
python scripts/prepare_minimax_voice.py --env-file D:/Code/Apps/.env --reference outputs/minimax-reference-20261025/reference.wav --prompt-audio outputs/minimax-reference-20261025/prompt.wav --prompt-text-file outputs/minimax-reference-20261025/prompt-text.txt --output outputs/minimax-reference-20261025/clone-receipt.json
```

本机 `FATFISH_MINIMAX_KEY` 有值后，同一命令加 `--apply` 才真正上传和复刻。回执不显示 Key；相同参考与示例已完成时不重复上传，变化后需使用新回执与新 voice ID。试听请求会按服务商字符计费。

复刻成功后，将确认的 voice ID 写入现有路由配置，沿用 1.1 倍语速；先验证真实音频再切换默认引擎。准备参数通过不代表服务端复刻、试听和 QQ 语音发送已通过。
