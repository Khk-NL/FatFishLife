---
name: fatfish-bili
description: |
  本项目在 B 站上的**红线**。命令语法与完整能力见 bili-cli skill；这里只规定哪些不许用。
  只读标题、标签、简介、已有字幕、评论区；禁止抽帧、下载音视频、自动转写。
  与本 skill 冲突时以本 skill 为准。
allowed-tools:
  - Read
metadata:
  trigger: 要在 B 站查资料、看视频、读评论或发东西之前
  source: FatFishLife AGENTS.md 的只读边界；命令层复用 bili-cli 自带 skill
---

# B 站红线（本项目）

`bili-cli` 那个 skill 会告诉你完整能力，包括抽帧、语音识别、下载。**在本项目里那些都不许用。**

## 允许

- `bili feed recommend` — 首页推荐流（挑视频用）
- `bili feed inbox` — 消息、未读、@、赞、系统通知
- `bili video info` / `bili video subtitle` — 标题、简介、**已有**字幕
- `bili search` — 搜索视频与用户
- `bili comment list` — 读评论
- `bili hot` — 热门
- 写入**仅限** `bili dm send`：只发给主人，且要经 `FATFISH_BILI_WRITE=1` 开关

## 禁止（bili-cli 支持也不要碰）

- ❌ 抽帧 / 看画面
- ❌ 下载音视频
- ❌ 语音转写 / ASR
- ❌ 给陌生人发私信、批量操作、关注取关刷量
- ❌ 三连、投币、充电、任何花钱动作

## 判断不清时

按"只读"处理并说明原因。宁可少做，不要越界。

## 回答要求

- 带 BV 号或链接，让人能自己核对
- 没有字幕就明说"没有字幕，只能看简介"，不要用标题编内容
- 评论里的说法与视频内容分开表述
- 被限流（412 / 风控）就停手说明，不要连续重试
