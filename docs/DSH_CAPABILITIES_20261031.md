# 外部能力接入与素材导入（2026-10-31）

这一轮把「外部内容能力」按能用的做、不能用的记清楚：表情素材导入、免费生图、B站动态、
贴吧/小黑盒的可用路径、QQ空间的真实门槛、B站投稿的硬限制。所有结论都来自实测，不是推测。

## 1. 表情素材导入（已完成）

源：`G:\素材╰(°▽°)╯\表情包大全（正在收录更新.....）全是up精心整理收集的`（5839 个文件 / 13 GB）

整体搬不现实（13 GB，多数是壁纸级大图），因此按人设相关性挑三套：

| 分类 | 取样规则 | 数量 |
| --- | --- | --- |
| 鲸鱼娘 | 动图 120 张（全量 gif 里挑最小的）+ ≤400 KB 静图 80 张 | 200 |
| 贴吧 | 全部（小图） | 93 |
| doro | 最小的 100 张 | 100 |

- 脚本：`scripts/import_sticker_assets.py`（用 `.tools/dsh-python/Scripts/python.exe` 跑）
- 落盘：`D:\Code\Projects\FatFishLife\data\memes\{鲸鱼娘,贴吧,doro}\`，共 **393 张 / 258 MB**
- 索引：`data/memes/semantic_metadata.json`，key 是内容 sha1，字段 `caption` / `tags` / `relative_path`；
  标签含分类名 + `动图`/`静图`，`fatfish_core/gallery.py` 的 `_memes_dir()` 兼容 `<root>/<分类>/` 布局
- 验收：MCP `meme_find("鲸鱼娘")` 返回 4 条带 tags 的真实文件

这个目录同时是「以后自己加图」的入口：往 `data/memes/<分类>/` 丢文件、在 metadata 里补一条，
`meme_find` / `meme_random` 立刻能选中，不用重启。

另有 `dsh-nekowhale-stickers@1.1.1`（322 张「大肥鱼」表情，自带 `sticker_search`/`sticker_send`），
桥已支持在回复里写 `[sticker:名字]` 直接发图。

## 2. 生图（已完成，免费）

`fatfish_memory_mcp.py` 新增工具 `image_generate(prompt, width=768, height=768)`：

- 默认接口 `https://image.pollinations.ai/prompt/{prompt}?width={width}&height={height}&nologo=true&seed={seed}`
  （免 key、免注册）；可用 `FATFISH_IMAGE_API` 换模板
- 落盘 `outputs/dsh-media/gen/<uuid>.jpg|png|webp`（`FATFISH_IMAGE_DIR` 可覆盖），按魔数判格式
- **速率限制（实测）**：`1 image every 45 seconds per IP`，超了返回 `HTTP 402 {"code":"FREE_LIMIT"}`；
  高峰期还会 503。工具内做了「402 直接告诉对方等 45 秒、429/503 等 3 秒重试一次」
- 生成后她会调 `qq_send_image` 发出去；提示词里写了「一次一张，别连着刷」

质量参考：768×768 卡通贴纸风格正常出图（约 30–40 KB，右下角有 pollinations 水印）。

## 3. B站动态（已接通），B站投稿（做不了）

- `bili dynamic post` 是 CLI 里唯一的内容发布接口（图文动态，`--image` 最多 9 张、`--at`、`--vote`）
- 新增 MCP 工具 `bili_dynamic_post(text, images="", dry_run=false)`，走 `fatfish_core/bili.py:post_dynamic()`，
  受 `FATFISH_BILI_WRITE=1` 门禁；`--dry-run` 实测返回 `{"dry_run": true, "action": "dynamic.post"}`
- **顺手修了一个真 bug**：MCP env 里从来没有 `FATFISH_BILI_EXE`，所以生产环境下所有 `bili_*` MCP 工具都在报
  `找不到 bili-cli：bili`。已在 `cordis.patch.yml` 的 `mcp-fatfish-memory.env` 补
  `FATFISH_BILI_EXE: 'D:/Code/Apps/bili-venv/Scripts/bili.exe'`，`bili_search("明日方舟 界园")` 现在真返回结果
- **投稿（上传视频）不可行**：`bili --help` 没有 upload 子命令，B站视频投稿需要浏览器端的分片上传 +
  实名认证，CLI 没有这条路。她说「投稿做不了，只能发动态」是事实，不是偷懒

## 4. 百度贴吧 / 小黑盒

| 目标 | 直连结果 |
| --- | --- |
| `tieba.baidu.com/f?kw=…` | 403（百度安全验证） |
| `tiebac.baidu.com`、`tieba.baidu.com/mo/q/m`、`/f/search/res` | 全 403 |
| `api.xiaoheihe.cn/bbs/app/link/tree?link_id=…` | `{"status":"failed"}`（缺 hkey 签名） |
| `api.xiaoheihe.cn/maxnews/app/share/detail/<id>` | 「该功能正在维护中」 |
| `web_search "site:tieba.baidu.com …"` | **可用**，返回标题 + 正文片段 |
| `web_search "site:xiaoheihe.cn …"` | **可用**，返回标题 + 正文片段 |

所以接入方式是「搜索代理」而不是「站点 API」：提示词里已经写明用 `web_search` 加 `site:` 限定，
再 `read_page` 读打得开的页面。不额外装插件（modsearch 的 `read_page` 对这两家是 403 / JS 渲染空正文）。

## 5. QQ 空间（说说）

NapCat 本身不发说说。可行路径是第三方桥 [`Gu-Heping/onebot-qzone`](https://github.com/Gu-Heping/onebot-qzone)
（OneBot v11，暴露 `qzone_publish` / `qzone_delete` / `qzone_get_posts` / `qzone_get_friend_feeds` 等 40 个 action，
默认监听 5700）。登录必须是 QQ 空间的 Cookie：

```
QZONE_COOKIE_STRING=uin=o<QQ号>; p_uin=o<QQ号>; skey=<skey>; p_skey=<p_skey>
```

或者 `QZONE_ENABLE_QR=1` 扫码。这一步**只能由老大本人做**（我不该、也不能登你的 QQ 空间）。
拿到 Cookie 后装桥、加一条 reverse 客户端指向 DSH，就能让她发说说了。

## 6. 花生AI / updream / 语音模型

- **updream**：聚合工作台，Pro ¥949/年（≈¥79/月，19800 积分/月），没有免费开放 API，接它等于再买一份订阅 → 不接
- **花生AI**：没查到可用公开 API 文档 → 不接
- **语音**：现有 MiniMax `speech-2.8-hd` + 复刻音色（`AppleLeVoice20261025`），复刻一次性 9.90 元、
  合成约 0.35 元/千字；`fatfish_core/tts.py` 还支持 `siliconflow` / `elevenlabs` 两个 provider，
  换 provider 只改 env（`FATFISH_TTS_PROVIDER`）不改代码。更便宜就走硅基流动（需要 key，可在凭证面板加）

## 7. 让她知道自己能用（提示词 + 白名单）

`dsh/runtime-adapter.mjs` 的 `SOCIAL_CHANNEL_PROMPT` 能力清单加到十条，新增：

- ⑧ 画图——`image_generate` 出图，再 `qq_send_image` 发出去
- ⑨ 贴吧 / 小黑盒——用 `web_search` 加 `site:` 限定，再 `read_page`
- ⑩ B站发动态——`bili_dynamic_post`，只有老大明确让发才发

白名单 `SOCIAL_MEDIA_TOOLS` 同步加入 `image_generate`、`bili_dynamic_post`（现共 15 个），
「没有的能力」那句补上「B站投稿视频都不行」，避免她假装能投。

## 8. 验证记录

- 表情：`meme_find("鲸鱼娘")` → 4 条真实路径
- 生图：`image_generate('chubby whale girl…')` → `outputs/dsh-media/gen/d06197ee….jpg`（39 662 字节，768×768）
- B站动态：`bili_dynamic_post(..., dry_run=true)` → `{"ok": true, "dry_run": true}`
- B站探测：`bili_check` 由 `找不到 bili-cli：bili` 变为 `{"exe": "...bili.exe", "writes": true}`；
  `bili_search("明日方舟 界园")` 返回 3 条真实视频
- 桥与控件重新打包（`fatfish-onebot-0.9.6-f221110a8ab6.tgz`），`lib/*.js`、`lib/*.mjs` 已落到
  `~/.dsh/profiles/desktop/node_modules/dsh-onebot-qq/lib/`，profile 依赖已指向新包；宿主重启后生效

## 9. 待办

- QQ空间：等老大给 Cookie 或扫码，之后装 `onebot-qzone` 并联调 `qzone_publish`
- 生图换更高质量：凭证面板加一个 key（硅基流动 / 智谱），把 `FATFISH_IMAGE_API` 指过去
- B站动态定时发布：控制层还没有 `runBiliDynamic` 任务，目前只能被她手动调用
- 贴吧/小黑盒若要读全文：需要带签名的逆向或常驻浏览器，性价比低，暂不做
