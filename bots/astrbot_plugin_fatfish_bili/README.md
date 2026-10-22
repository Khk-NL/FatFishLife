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

## 记忆

写入 `astrbot_plugin_fatfish_memory` 的同一个 SQLite：

- 收件箱、看过的视频：`public`
- 私信：`private`

`enable_inbox_poll` 默认关闭。开启后每 `poll_interval_seconds` 秒调用一次 `bili feed inbox`，会消耗 B 站未读状态。

## 注意

- bili-cli 自带评论 10 秒/次、私信 10 秒/次等本地限流，遇到风控会直接报错，不重试。
- 视频投稿在阶段 1 完成后接入，这里暂不提供 `/bili 投稿`。
