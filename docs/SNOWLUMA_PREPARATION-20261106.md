# SnowLuma 协议端准备（未切换账号）

本单元保留 FatFishLife 现有 `dsh-onebot-qq 0.9.6` 适配桥、记忆、人格、媒体与任务工作流，只准备另一个 OneBot v11 协议端。没有安装 SnowLuma，没有引入 NoMind 的第二套桥接引擎，也没有登录或发送 QQ 消息。账号暂停仍须保持；离线验证不能证明 QQ 已解限或真实收发正常。

## 已核对版本与边界

- 官方发行版：[SnowLuma v2.4.0](https://github.com/SnowLuma/SnowLuma/releases/tag/v2.4.0)，2026-11-03；Windows x64 完整发行包为 ZIP，自带 Node。这里只记录来源，不下载或分发其二进制。
- [源码许可](https://github.com/SnowLuma/SnowLuma/blob/v2.4.0/LICENSE)为源码可见非商业许可，不是 OSI 开源许可；原生组件为专有组件。没有把其代码或组件复制进 FatFishLife。
- [EULA §5.4](https://github.com/SnowLuma/SnowLuma/blob/v2.4.0/EULA.md)原文：

  > 通过自动化脚本部署……均须事先取得书面授权。

  本仓库不自动安装、部署或接受其协议。发行说明中的无人值守协议确认变量不能代替上述授权。
- [QQ 兼容 manifest](https://github.com/SnowLuma/SnowLuma/blob/v2.4.0/compat/qq.json)没有列出已验证版本，`allowUnknown=true` 只表示允许尝试。不能据此保证现有 QQ 版本兼容，也没有证据表明比 NapCat 更少触发账号限制。

## 手动配置模板（全部未启用）

模板位于 `dsh/templates/snowluma-v2.4.0/`，分别对应官方 `config/onebot.json`、`config/runtime.json`。结构依据[官方配置文档](https://github.com/SnowLuma/SnowLumaDocs/blob/main/content/docs/guide/configuration.mdx)及[v2.4.0 反向 WS 实现](https://github.com/SnowLuma/SnowLuma/blob/v2.4.0/packages/onebot/src/network/ws-client-adapter.ts)。这些文件只是配置示例，不由启动脚本读取，不复制到任何运行目录。

- `wsClients` 目标使用现有生产桥的 `ws://127.0.0.1:8646/ws`；`Universal` 同时承担事件和动作，消息为段数组。
- HTTP、正向 WS 和反向 WS 项均为 `enabled:false`，监听地址只写回环。空 token 仅为待手动填写的占位，不是可启用配置，不含真实账号或凭据。
- `hookAutoLoad:false`；没有启用任何账号。SnowLuma 没有通用 `accountEnabled` 字段，不能靠虚构字段禁用账号；模板通过不部署、不注入和禁用全部网络项保持未接入。
- 账号级 `config/onebot_<uin>.json` 会覆盖全局配置；将来手动安装时必须核对实际账号配置，不能把全局模板当作已禁用已有账号的证据。
- 模板不控制 WebUI 的监听地址；官方此 runtime schema 只有端口和 hook 开关，因此不能据本模板宣称 WebUI 已限制为回环。未来手动启动前仍需核验实际绑定。

未来手动验收时，保持原 DSH 桥与会话数据不变：先停止原协议端对同一反向 WS 的连接，再仅为目标账号设置一个反向 WS 客户端，私下填入与 DSH 相同的非空 token。SnowLuma 发出标准 Bearer、`X-Self-ID`、`X-Client-Role`。不能让两个协议端同时接管，也不能在账号暂停期间启用或试发消息。

## 本次薄适配

SnowLuma 的 [`get_record(out_format="mp3")`](https://github.com/SnowLuma/SnowLuma/blob/v2.4.0/packages/onebot/src/actions/extended.ts#L1581-L1657)保留原始 file/url，另附转码后的 base64；旧桥只保留 file，hash-only 语音可能无法进入 STT。本地打包脚本现在保留四个字段，仅对 voice、明确 MP3 的 base64 回执进行格式和大小检查，再复用现有 `base64://` 媒体临时目录及 TTL 路径。上限取现有下载上限与 15 MiB 语音上限中较小者。NapCat 的 file:// 后备路径保留，URL 仍经过原下载器与 SSRF 检查，不增加新下载器或任意文件读取入口。

打包仍从完整性锁定的上游 0.9.6 内容重建，精确锚点不匹配就失败；不修改上游原始包或 SnowLuma 组件。

## 验收与待办

离线测试覆盖 hash-only MP3 字节与后缀、坏格式/超限拒绝、NapCat file://、URL 的原 SSRF 门和模板默认禁用。测试使用临时目录、模拟 OneBot 回执，并替换测试副本的图片渲染入口避免加载原生画布；不访问 QQ、云模型或原生客户端。

仍待真实账号恢复后的独立验收：QQ 版本与注入、反向 WS 握手和心跳、文字/图片/语音播放、发送回执；不能把 mock 通过写成真实兼容通过。

普通文件 API 仍待单独适配：SnowLuma [`get_file`](https://github.com/SnowLuma/SnowLuma/blob/v2.4.0/packages/onebot/src/actions/extended.ts#L3629-L3680)只查图片/语音缓存，群文件需 `get_group_file_url`；私聊文件应保留原消息的 `user_id/file_hash`，见[`get_private_file_url`](https://github.com/SnowLuma/SnowLuma/blob/v2.4.0/packages/onebot/src/actions/group-file.ts#L566-L605)。本单元没有声称普通文件收取已兼容。
