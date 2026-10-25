# QQ 语音策略

2026-10-25 手动请求修复：明确“发语音、用语音回答、语音呢”不抽随机概率，也不受自动语音5字下限限制；180秒冷却、80字上限、节能、会话权限仍保留。未获允许、冷却或合成失败会明确提示原因，不再只回文字却让人以为语音已发送。当前允许苹果乐乐乐群和老大主号私聊；其他群/私聊须自行在原插件会话范围中开启。本轮未提高随机概率。

沿用已安装的 [TTS Emotion Router 3.3.3](https://github.com/muyouzhi6/astrbot_plugin_tts_emotion_router)（MIT）。MiniMax 合成、情绪映射、概率判断、会话冷却、长度检查和历史记录都继续由该插件处理；FatFish 只补节能门禁、并发限制及发送保护，不创建第二套 TTS 提供商。

`scripts/configure_voice_policy.py` 只接受已核对的 3.3.3 源码形态，默认预览。部署前停止 AstrBot，再运行：

```powershell
python scripts/configure_voice_policy.py --astrbot D:\Code\Apps\AstrBot --apply
```

它在本机私有目录备份原文件，在现有 router 的两个方法上增加薄装饰器，更新同一个插件的 WebUI 配置说明。不改 DeepSeek、人设、记忆、开场对话或群聊参与概率，也不创建额外数据库和队列。再次执行没有差异时不重复备份或写入。若社区插件升级导致接口不同，脚本会停止，需先审查新版本。

配置位于 AstrBot `data/config/astrbot_plugin_tts_emotion_router_config.json` 的 `fatfish_policy`：

| 字段 | 初始值 | 用途 |
|---|---|---|
| enabled | false | 总开关；真实付费验收与日常自动消费分开授权 |
| voice_probability | 0.10 | 已决定参与且已生成回复后，转语音的概率 |
| voice_probability_step | 0.0 | 每次符合语音条件但没有发送成功后增加的概率；由用户填写 |
| voice_probability_max | 1.0 | 递增概率上限；由用户填写 |
| cooldown_seconds | 180 | 每个完整会话独立冷却 |
| max_text_length | 80 | 超长回复保持原文 |
| manual_trigger | true | “用语音回复”等明确请求跳过概率，仍受冷却/长度/节能/会话门禁限制 |
| fallback_to_text | true | 合成或发送失败时保留已生成的原文 |
| text_alongside_voice | false | 是否同发原文与语音 |
| disable_during_economy_mode | true | 读取既有 offline/signal，节能时不调用付费 TTS |

以上参数可在现有 router 的 WebUI“FatFish lightweight voice policy”中修改。概率仍调用 router 原有检查器，不做两次随机判断；这与群聊参与概率完全独立。自然语言明确要求文字时，本轮保持文字。

有效语音概率为 `min(voice_probability_max, voice_probability + n * voice_probability_step)`。三个概率值都填 **0～1的小数**，例如0.10代表10%，0.02代表每次增加2个百分点。基础值仍为当前0.10；新增步长默认0，保持原有频率，具体数字由用户填写。可自行设置为0.10/0.02/0.30，对应10%→12%→14%……最高30%，这只是调节示例，不会自动写入。

`n`按完整会话标识独立统计，与表情包及搭话计数互不影响：只有通过白名单、会话、节能、长度、混合内容和冷却门禁的回复尝试才计数；概率未中、合成失败、语音发送失败都计为一次未发。冷却中、离线中或用户明确要文字时不积累，避免恢复后突然高概率发声。只有实际Record发送成功才归零，抽中概率或生成了文件不归零；明确请求的语音成功发送也会重置。计数只在本进程内保留，重启归零，最多保留512个会话，无聊天正文。

2026-10-25用户已明确授权开启日常语音并接受后续按量费用，日常开关现已开启。白名单仅包含已确认的“苹果乐乐乐”完整会话；10%概率、180秒冷却、最多80字，节能时关闭。MiniMax 使用 `AppleLeVoice20261025`、1.0倍语速；旧硅基情绪音色映射保留在配置/备份中，但其路由暂时关闭，避免把旧服务的音色URI传给MiniMax。后续复核情绪映射后再启用。

只有确认日常自动语音的消费安排后，才使用 `--enable --apply`，并在 router 原生会话名单中允许目标 UMO。仅把 `fatfish_policy.enabled` 改为 true 不能绕过 router 的会话名单或 AstrBot `/tts` 会话开关；禁用任何一层都会阻止合成。MiniMax 密钥和 Voice ID 仍在 `tts_engine.minimax`，适配脚本保留这些值且不会输出。原生全局 TTS 应关闭，避免与社区 router 重复合成。

首次将已复刻音色写入配置可同时传 `--key-file <本机密钥文件> --clone-receipt <成功回执>`；脚本只把密钥写到原路由的私有配置，不输出或提交。`--umo napcat:GroupMessage:<已确认群号>`可增加明确会话。配置会先备份并读回，并关闭原生全局 TTS；不改已有LLM提供商或角色卡。关闭日常语音用不带 `--enable` 的同一配置命令，或在WebUI同时关闭 `fatfish_policy.enabled` 与 `feature_policies.voice_output.enable`。

普通回复仍交给原 LLM/离线模块。只有现有回复进入最终发送阶段时，策略才决定是否转音；不会为语音再生成一份回复，也不会因失败重调 LLM。直接 `/tts` 命令复用社区实现，同样检查节能、冷却和长度。

同时最多两次合成，每个完整 UMO 同时一个，忙时保留文字而不排队。公开群聊发送语音前会明确发送“AI合成角色语音”，不冒充真人；语音仍走原 AstrBot/NapCat `event.send`，Record 独立发送。发送失败会尝试原文一次；若原文同时发送功能已开，则避免再补一份重复文字。

每个发送事件从 router 音频缓存复制独立的临时副本，再把 Record 指向该副本，避免两个会话说同一句话时互相删除共享缓存。发送完成后只清理自己创建的发送副本，原缓存继续交由上游 TTL 清理；不删除原始素材或其他目录文件。Windows 暂时锁住的副本也交由社区插件既有 TTL 清理器处理，没有新增清理定时器。部署时应保持 router 自带的定时清理启用。

本地模拟验收覆盖节能/关闭/长度/会话名单拦截、明确语音请求、拒绝语音、并发限制、群聊 AI 标识、发送失败回退、双输出去重与临时文件范围。真实音色、听感和 QQ 播放仍以实际账号验收为准。
