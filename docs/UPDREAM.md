# Updream 本地交接

截至 2026-10-23，已核实 [Updream 官方登录页](https://www.updream.cn/login) 和 [公开首页](https://www.updream.cn/)。公开页面将产品描述为哔哩哔哩自研 AI 视频创作产品，并提供剧本、角色、分镜等创作入口；登录需要实际账号。

本轮没有找到可核实的官方公开 API 文档。不能据此断言平台没有 API，也没有把第三方转发服务当成官方接口。账号内的创建、生成、导出以及用户协议与素材授权，尚未完成实机验证。

## 已能使用的本地流程

先用现有文案工具生成并校验项目，再导出给 Updream 使用的分镜和素材包：

```powershell
python scripts/updream_handoff.py export examples/single.json outputs/updream/single-handoff
```

输出包含 `storyboard.md`、`handoff.json` 和该项目明确引用的素材副本。它保持场景顺序、时长、角色引用和字幕时间；不会读取私人记忆、上传素材、调用 Updream 或消耗平台积分。目标目录存在时拒绝覆盖。

在已登录的 Updream 页面中，按分镜包选择素材并创建项目。实际生成参数、版权、肖像及音乐授权由创作者确认；包中的 `rights_confirmed` 保持 `false`，不会自动替你确认。

将页面导出的成片保存到本机后，可检查媒体信息并完整解码：

```powershell
python scripts/updream_handoff.py verify-export outputs/updream/export.mp4 outputs/updream/export.verified.json
```

验证成功返回 `status: validated` 和分辨率、帧率、时长、音轨信息，失败不写通过报告。该报告只证明本地媒体可解码，不表示作品获准发布，也不伪装成模板引擎的 `status: completed` 渲染报告。当前投稿适配器只接受模板引擎的成功报告，不能直接使用这份验证报告；账号持有人完成真实导出验收后，再据实际样本确定发布转接方式。

## 留给账号持有人的验收

- 登录已有账号，确认可创建项目、选择生成模型和导出；确认实际费用与剩余额度。
- 阅读账号内当前用户协议、知识产权与合规声明，确认所用游戏素材、人物肖像及音乐的授权和外部使用范围。
- 用一条短片完成从分镜包到生成、导出、完整解码的实测，并确认角色连续性、字幕、音乐和画面效果。
- 若账号提供官方 API 或明确允许自动化的接口文档，再据文档实现接入；本轮未逆向账号接口或自动点击付费生成。
