# 硅基流动语音提供商

插件加载时注册 AstrBot 原生 `fatfish_siliconflow_tts` 提供商类型。它本身不会创建或启用 provider，也不会修改默认语音、密钥或其他配置。在 AstrBot 的语音合成提供商中手动添加该类型，填写硅基流动 `api_key`，确认后选择为 TTS；原来的 Edge TTS 可以保留备用。

配置项为 `api_key`、`api_base`、`model`、`voice`、`speed`、`timeout`。默认模型 `FunAudioLLM/CosyVoice2-0.5B`，默认声线 `FunAudioLLM/CosyVoice2-0.5B:diana`，语速 `1.1`，比标准速度稍快；可以换成已注册的自定义声线。diana 是服务预置女声，不等于能天使原声或已完成角色声音复刻。

请求发到 `https://api.siliconflow.cn/v1/audio/speech`，显式传入 `speed` 与 `response_format=wav`。服务的流式 WAV 头可能使用未完成的长度，插件用已有 FFmpeg 忽略该长度，重新写为 24kHz、单声道、16bit PCM WAV，并实际读取帧数验证。转换失败、HTTP 错误或超时会直接失败，不返回原始 WAV 冒充有效长音频，不自动改用其他声音。

依赖 AstrBot 已有的 `httpx` 和项目视频工具使用的 FFmpeg，无需新安装依赖。生成音频放在 AstrBot 原生临时目录；原始响应临时文件和失败产物会清理。测试覆盖请求的模型、声线和语速、错误传播，以及带错误长度的 WAV 实际规整。真实角色声线和 QQ 播放效果仍需本人听验。

参数依据：[硅基流动语音生成 API](https://docs.siliconflow.cn/docs/api/audio-speech-post)、[语音合成说明](https://docs.siliconflow.cn/docs/userguide/capabilities/text-to-speech)。
