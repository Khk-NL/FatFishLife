# astrbot_plugin_fatfish_bili

用 bili-cli 驱动 B 站账号，和 QQ 共享记忆。

## 依赖

```powershell
python -m venv D:/Code/Apps/bili-venv
D:/Code/Apps/bili-venv/Scripts/pip install bili-agent
```

插件配置 `bili_exe` 指向 `bili.exe`，`bili_home` 指向独立配置目录（登录、限流、审计都留在这里）。

## 登录

```
/bili 登录
/bili 确认
```

二维码默认 180 秒有效。登录成功后把 `owner_uid` 设为主人 UID。

## 命令

```
/bili 状态
/bili 收件箱
/bili 看 BV1xx411c7mD
/bili 搜 关键词
/bili 回复 <BV号> <评论ID> <内容>
/bili 私信 <UID|owner> <内容>
/bili 记忆 <关键词>
```

`dry_run_writes` 默认 `true`：评论和私信只返回 bili-cli 的预览，不真正发送。

登录、确认、状态、收件箱、立即处理消息和发送私信，仅限主人或 AstrBot 管理员在私聊中使用。QQ 主人身份同时校验平台和 `owner_qq`，其他平台的同号用户不会获得权限。公开视频查看、搜索和公开记忆检索继续可用。

## 记忆

写入 `astrbot_plugin_fatfish_memory` 的同一个 SQLite：

- 看过的视频、公开评论回复：`public`
- 收件箱（包含私信和系统通知）、私信：`private`

`/bili 记忆` 在群聊或非主人会话中只检索公开记录；私人记录仅向主人或管理员的私聊开放。LLM 的 `bili_inbox` 工具遵循同样的权限检查。共享记忆插件重新加载时，会把旧版错误标成公开的 B 站收件箱记录转回私人层；B 站查询也会排除这些旧收件箱记录的公开访问。

后台通知可以保留公开评论回复，但只报告私信已处理，不附带私信正文或回复内容；完整结果通过主人私聊中的 `/bili 处理` 查看。

`enable_inbox_poll` 默认关闭。开启后每 `poll_interval_seconds` 秒调用一次 `bili feed inbox`，会消耗 B 站未读状态。

## 注意

- bili-cli 自带评论 10 秒/次、私信 10 秒/次等本地限流，遇到风控会直接报错，不重试。
- 视频投稿在阶段 1 完成后接入，这里暂不提供 `/bili 投稿`。
