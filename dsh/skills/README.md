# FatFishLife skills

这些 skill 把 AstrBot 时期的**行为边界**带过来，而不只是工具：光有 MCP 工具，模型不会知道
「B 站只能读、不能抽帧」「候选记忆不等于事实」。

## 安装

DSH 从用户目录加载 skill，仓库里只是源码。装法是把目录复制过去：

```powershell
Copy-Item dsh\skills\fatfish-bili  "$env:USERPROFILE\.claude\skills\fatfish-bili"  -Recurse -Force
Copy-Item dsh\skills\fatfish-memory "$env:USERPROFILE\.claude\skills\fatfish-memory" -Recurse -Force
```

装完需要新开一个会话才会出现在技能目录里（技能表在会话启动时读取）。

## 现有

| skill | 管什么 | 依赖的工具 |
| --- | --- | --- |
| `fatfish-bili` | B 站只读查询与引用；禁抽帧/下载/转写 | `bilibili_search` / `bilibili_video` / `bilibili_subtitles` |
| `fatfish-memory` | 记忆召回、候选写入、按群隔离、不把候选当事实 | `recall` / `remember` / `candidates` / `review` / `search` |

## 还没迁

- 运营规矩（推荐理由、21:00 标签学习、23:50 日记动态）目前只在 `dsh/rules.md`，**没有执行器**，
  也没有做成 skill —— 它需要定时触发，不是提示词能解决的。
- 视频创作（Updream）流程未迁。
