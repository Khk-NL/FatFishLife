# MiniMax 音色复刻与 QQ 接入（2026-10-25）

沿用已安装的 [TTS Emotion Router 3.3.3](https://github.com/muyouzhi6/astrbot_plugin_tts_emotion_router)（MIT）及其 MiniMax 客户端、Hex 解码、音频校验和缓存，不新增语音插件或提供商。项目只补语音策略与发送保护，见 [VOICE_POLICY.md](VOICE_POLICY.md)。DeepSeek、人设、记忆及开场对话不修改。

用户已在本线程确认素材用于上传、复刻和 QQ 群使用的授权；复刻验收预算10元，最多一次复刻与三条普通试听。2026-10-25另行明确授权开启日常语音并接受后续按量费用，当前已启用；此后日常费用独立于原10元验收预算。

## 两种上传用途

| 用途 | 要求 | 作用 |
|---|---|---|
| `voice_clone` | 10 秒～5 分钟，mp3/m4a/wav，不超过 20 MB | 必需的音色参考，上传后取得 `file_id` |
| `prompt_audio` | 小于 8 秒，同样不超过 20 MB | 可选示例；通过 `clone_prompt.prompt_audio` 和对应 `prompt_text` 一起提交 |

两者都调用 `POST /v1/files/upload`，通过 `purpose` 区分，然后调用 `POST /v1/voice_clone`。可选短句不能代替长参考。来源：[上传复刻音频](https://platform.minimax.cn/docs/api-reference/voice-cloning-uploadcloneaudio)、[上传示例音频](https://platform.minimax.cn/docs/api-reference/voice-cloning-uploadprompt)、[音色复刻](https://platform.minimax.cn/docs/api-reference/voice-cloning-clone)。

## 本轮真实结果

素材目录为 `D:/EdgeDownload/minimax_applele_samples/`；其中 `minimaxAPI.env` 实际是单行密钥，脚本兼容这种格式，不输出内容。检查报告在忽略目录 `outputs/minimax-20261025/audio-inspection.json`。

- 四个短 WAV 分别2.58、5.13、1.86、1.95秒，均不能当主参考。
- 两份截短 M4A 为290.219、288.107秒，均合规；原版原始合集184.917秒、7.37 MB，同样合规。
- 选用原版合集为主参考，用户的 `01_original_assistant.wav` 为示例；示例PCM与原版1.10～3.68秒完全一致，文本按PRTS及已有同源转写核对为“老板，安排点差事给我们吧。”。新约文本“了/啦”未核实，不用于本次复刻。
- 22.5秒短主参考直接上传用时1.438秒；184.917秒长主参考用时2.219秒；示例上传1.313秒。三个上传均HTTP 200、`base_resp.status_code=0`，保存真实file_id；不使用示例ID。
- 仅发起一次最小复刻，16.203秒返回业务码0，Voice ID为 `AppleLeVoice20261025`；未在复刻请求中额外生成试听。
- 三条用户指定普通文本均通过现成客户端真实合成并完整解码；实际MP3、32000 Hz、单声道，约4.86、3.6、3.8秒，以回执实测为准。语速1.0、音量1.0、音高0，非流式，Hex已转为二进制音频。

本轮服务返回计费字符数35、16、28，共79；按当前官方单价，首次使用音色9.90元加79字符合成约0.02765元，合计**估算9.92765元**，不是平台账单读数。未进行付费情绪或语气词追加测试。[官方定价](https://platform.minimax.cn/docs/pricing/overview)

网页的 `unable to complete request` 没有HTTP/业务回执，无法追溯具体根因；本次短、长参考通过直接API均成功，不能据此把旧网页报错解释成音频规格错误或复刻失败。

回执：`upload-comparison.json`、`clone-receipt.json`、`tts-receipt.json`，均在上述忽略目录；音频在其 `audio/` 中，密钥不在回执内。首次正式TTS已调用音色，避免仅复刻未使用而7天过期。

## 配置和复用

- 现有路由：AstrBot `data/config/astrbot_plugin_tts_emotion_router_config.json`，`tts_engine.minimax` 保存本机密钥、Voice ID和参数，`fatfish_policy` 保存概率/冷却等策略。
- 独立非密钥配置：`data/plugin_data/astrbot_plugin_fatfish_voice/minimax-voice.json` 保存已确认 Voice ID、模型、参考摘要及语速。
- 开放平台URL为 `https://api.minimax.cn/v1/t2a_v2`；开启音频AIGC标识，群发送前另有“AI合成角色语音”文字。
- 首次接入关闭原生全局TTS，避免原生硅基语音和社区MiniMax重复转换；旧提供商、参数和配置备份保留。
- 日常语音已获授权并开启，仅允许“苹果乐乐乐”完整会话；概率10%、每会话冷却180秒、最多80字，节能时关闭。普通文本与节能回复继续运行；该概率只处理已经生成的回复，不影响群聊参与概率。

QQ实测：原生 AstrBot `AiocqhttpMessageEvent.send_message` 将 Record 编码后经已连接 NapCat 发送，仅向“苹果乐乐乐”发送AI标识及一条已生成试听。真实语音消息ID `1893361501`，`get_msg`读回Record，`get_record`取回转换音频并通过完整解码。该步骤没有合成请求，客户端人工播放/听感尚未确认。临时验收helper已恢复并禁用。

验证：最终全套535项测试通过，其中本次上传/策略/预算与编码核验相关22项通过。现有路由的实际配置解析函数验证默认音色为本次Voice ID、速度1.0；对部署前后原生LLM提供商配置及角色提示词做摘要对比，均一致。语音失败和发送失败使用已有原文，不再次调用LLM。首次官方API实际调用与QQ真实发出均独立记录，不用模拟结果替代。

## 可重复的操作

预览参数与文件校验，不联网上传：

```powershell
python scripts/prepare_minimax_voice.py --env-file D:/EdgeDownload/minimax_applele_samples/minimaxAPI.env --reference <合规主参考> --prompt-audio D:/EdgeDownload/minimax_applele_samples/01_original_assistant.wav --prompt-text-file outputs/minimax-20261025/prompt-text.txt --output outputs/minimax-20261025/clone-receipt.json
```

默认只检查。真实操作还需 `--authorized --budget-cny 10 --apply`；已有成功回执直接复用，上传成功逐步落盘。仅上传网络故障最多重试一次；复刻请求不自动重试，结果不明时先核查平台音色列表，防止重复付费。降噪和归一化初始均false，不传不需要的 `text_validation/accuracy`。

`scripts/verify_minimax_voice.py` 复用已装路由，只允许三条固定试听，付费调用前记账保留，错误或结果不明不自动再调；已有成功音频复用，不新增费用。`scripts/verify_qq_voice.py` 从既有验收helper复用原生发送器，只向“苹果乐乐乐”发送一个既有样本，独立核验登录账号、群名、离线状态和Record回读，不再合成。

修改文件清单：

- `scripts/prepare_minimax_voice.py`：requests multipart、真实响应审计、断点回执、单次复刻与权限/预算门禁。
- `scripts/configure_voice_policy.py`：复用社区路由的幂等薄适配、配置迁移和本机备份。
- `scripts/verify_minimax_voice.py`：限三条试听、按量预估、完整解码与编码核验，不自动重试付费操作。
- `scripts/verify_qq_voice.py`：限定目标的原生QQ发送与Record回读。
- `fatfish_core/voice_policy.py`：节能门禁、现成策略复用、发送失败回原文和独立临时副本。
- `tests/test_minimax_voice_setup.py`、`tests/test_voice_policy.py`、`tests/test_verify_minimax_voice.py`：对应本地回归。
- `docs/MINIMAX_VOICE.md`、`docs/VOICE_POLICY.md`、`docs/FEATURE_AUDIT-20261024.md`、`docs/handoff-20261024.md`：接口、配置、验收结果和限制。

真实QQ客户端听感仍需本人验收；API发送、回读及可解码与真人客户端试听分开记录。
