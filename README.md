# FatFishLife

第一阶段：Windows 本地模板视频工具。复用角色合成图、手写字幕和本地音乐，输出 MP4、封面、SRT 及可供后续程序读取的结果报告。

## Web 拼贴测试版

```powershell
python -m fatfish_video serve
```

浏览器打开 **http://127.0.0.1:8765**。需要换端口时加 `--port 8766`，终端按 Ctrl+C 停止。页面和媒体接口只监听本机，不需要 Node、模型或平台账号。

1. 搜索内置的 **88 个具名角色条目**，选择头像或半身图，也可以导入自己的角色图片。角色名、英文标签及 ID 均可搜索。
2. 默认叠加从用户参考图提取的牢大脸。拖动位置，调整宽高、角度、羽化及取脸范围；用“保留头发画笔”画回刘海、眼镜和饰品，擦除或撤销可以修改修补。支持替换脸部素材。
3. 导入本地音乐，手动调节 **0.5～2 倍速度**和音量，实时试听；默认随加速升调，也可勾选“保留原调”。“载入测试音乐”使用原创合成音乐。
4. 导出 1024×1024 PNG（可选透明背景），或导出调速后的 WAV。填写字幕、设置 2～30 秒时长后，可生成 1920×1080、30fps 的 MP4，在页面预览和下载。

这版使用可编辑的椭圆脸部拼贴，**没有自动人脸识别、五官对齐或 AI 换脸**。内置角色图有不同头部角度，不保证全部严格正面；换角色后需要手动贴合，原素材不会被覆盖。参考线不会导出，视频字幕单独叠加，视频默认有轻微推近和音乐结尾淡出。

图片编辑和试听在浏览器完成；点击音乐或视频导出后才传入本机 Python 服务。上传文件单个最多 50 MB。生成媒体在 `outputs/web/`，中间素材及生成配置在 `.web-data/`；均只保存本机，后者已加入忽略文件。刷新页面不会恢复尚未导出的编辑。

内置图片来自 [StarRailRes](https://github.com/Mar-7th/StarRailRes)，已缓存到 `assets/characters/`，离线也能搜索和使用；排除了主角昵称占位项。需要更新本地角色库时执行 `python scripts/sync_characters.py`（需要联网，只补下载缺失图片）。图标来自 [Lucide](https://lucide.dev/)，许可在 `assets/icons/LICENSE`。用户原始附件仍保留在 `assets/originals/`，取脸结果单独保存为 `assets/web/kobe-face.png`。

## 直接运行

在项目目录执行（Python 3.11 或更高版本，无第三方 Python 运行依赖）：

```powershell
python -m fatfish_video doctor
python -m fatfish_video validate examples/single.json
python -m fatfish_video render examples/single.json
python -m fatfish_video render examples/dialogue.json
python -m fatfish_video render examples/news.json
```

本机已配置 `.tools/ffmpeg/bin/`，并已生成三条样片：

| 模板 | 配置 | 成片 |
| --- | --- | --- |
| 单人吐槽 | `examples/single.json` | `outputs/single.mp4` |
| 双人对话 | `examples/dialogue.json` | `outputs/dialogue.mp4` |
| 角色搭配资讯图 | `examples/news.json` | `outputs/news.mp4` |

每条 12 秒、1920×1080、30fps。样片使用用户提供的角色图和**原创合成测试 BGM，不是崩铁音乐**。换真实音乐只需修改 `music.path`。原始附件保存在 `assets/originals/`；蓝底色差及原图拼贴边缘有意保留，没有自动抠蓝。

已有成片默认不会被覆盖。修改配置后显式重新生成：

```powershell
python -m fatfish_video render examples/single.json --overwrite
python -m fatfish_video render examples/single.json --output outputs/my-video.mp4
python -m fatfish_video probe outputs/my-video.mp4
```

命令成功返回 0、stdout 输出 UTF-8 JSON，进度及错误写 stderr；失败返回 1。`validate` 校验结构、素材引用、路径、时间及布局，不实际解码媒体；`render` 完成真实合成和媒体检查后才返回成功。

## FFmpeg 与中文字体

换电脑时需要完整的 `ffmpeg`、`ffprobe`，以及支持 libass 字幕和 libx264 编码的构建。

- Windows：从 [FFmpeg 官方下载页](https://ffmpeg.org/download.html) 指向的 [Gyan Windows 构建](https://www.gyan.dev/ffmpeg/builds/) 获取 essentials 包，将两个 exe 放入 `.tools/ffmpeg/bin/`，或把其 bin 目录加入 PATH。本机实际验证版本为 9.0.2。
- Linux：安装发行版提供的 FFmpeg 和 Noto Sans CJK 字体。本阶段尚未进行 Linux 运行验证。
- 也可使用 `--ffmpeg`、`--ffprobe` 指定程序，或设置 `FATFISH_FFMPEG`、`FATFISH_FFPROBE`。明确指定的路径无效时会报错，不会悄悄换工具。

Windows 默认使用微软雅黑；Linux 查找 Noto Sans CJK。自定义字体在 `subtitles` 中同时提供 `font` 文件路径及真实 `font_name` 家族名。字体文件只在合成时临时使用，不随项目复制分发。

## 项目配置

JSON 使用 UTF-8，所有素材路径及 `output` **相对 JSON 文件所在目录**；命令行 `--output` 相对当前工作目录。

```json
{
  "schema_version": 1,
  "title": "今天的整活",
  "canvas": {"width": 1920, "height": 1080, "fps": 30, "background": "#5AA6CF"},
  "template": "single",
  "assets": {
    "red": "../assets/originals/role-red.jpg"
  },
  "music": {
    "path": "../assets/music/demo-original.wav",
    "speed": 1.25,
    "pitch": "follow_speed",
    "volume": 0.65,
    "loop": true,
    "fade_in": 0.3,
    "fade_out": 0.7
  },
  "scenes": [
    {"duration": 4, "roles": ["red"], "caption": "孩子们，今天的主包又开工了。", "zoom": 0.015}
  ],
  "output": "../outputs/my-video.mp4"
}
```

### 模板与图层

`single` 放一个角色；`dialogue` 放一至两个角色；`news` 放一个角色，必须提供 `panel` 素材 ID。每个场景可用 `template` 覆盖项目默认值。

- 素材可写成文件路径字符串，也可写成 `{"path":"file.png","crop":[x,y,width,height]}`，crop 使用原图像素坐标。原文件不会修改。
- `roles` 是素材 ID 数组。自定义位置时写 `{"asset":"red","box":[0.1,0.15,0.4,0.7]}`。box 为画布内的相对 `[x,y,width,height]`，图片保持比例并在框内底对齐。
- `panel` 同样支持素材 ID 或带 box 的对象，框内保持比例居中。角色位于配图上层，字幕位于最上层。
- 支持 JPEG、PNG、WebP、BMP。透明 PNG 保留透明通道；带蓝底 JPEG 保留蓝底，避免损伤蓝色头发和衣服。
- `zoom` 为场景轻微推近幅度，默认 0.015，范围 0～0.10；设 0 关闭。字幕不随画面缩放。

### 字幕与时长

`caption` 表示整段场景的一条字幕；需要分句时使用 `captions`，两者不能同时出现：

```json
"captions": [
  {"start": 0, "end": 2, "text": "第一句"},
  {"start": 2, "end": 4, "text": "第二句\n显式换行"}
]
```

时间为场景内相对秒数，按输出帧率对齐到最近一帧；字幕需按顺序排列且不可重叠。默认黄字、黑描边、底部居中，中文自动换行；超过三行会要求拆句，避免覆盖大部分画面。可用 `subtitles.font_size` 调整字号。

### 音乐

`speed` 支持 0.5～2 倍；`pitch: "follow_speed"` 随加速升调，`"preserve"` 变速保调。`start` 是从源音乐跳过的秒数，`volume` 为音量倍数。默认循环播放；`loop: false` 时短音乐结束后补静音，视频时长保持不变。成片结尾按配置淡出。

省略 `music` 或设为 null 时输出静音音轨。示例音乐可通过 `python scripts/make_examples.py` 重新生成；该命令也会重新写入三份示例 JSON。

## Python 调用入口

```python
from fatfish_video import load_project, render_project

project = load_project("examples/single.json")
result = render_project(project, output="outputs/custom.mp4")
print(result.as_dict())
```

`render_project` 可接收配置路径或 Project，返回视频、封面、字幕、报告、时长、分辨率、帧数及是否有音乐。失败抛出 `ProjectError` 或 `RenderError`，不会返回成功结果。默认拒绝覆盖，明确传 `overwrite=True` 才替换输出。导入模块不会启动任务。

`.result.json` 的 `status` 仅在实际编码、音轨合成、ffprobe 检查和封面生成成功后写为 `completed`。后续发布模块应接收成功返回的 RenderResult，不以“某个旧 MP4 存在”判断本次任务成功。

## 验证

```powershell
python -m unittest discover -s tests -v
```

测试涵盖配置错误、相对路径、整帧时间轴，以及真实编码后的帧数、中文字幕像素、图层切换、音频升调/保调、短音轨补齐、覆盖保护和失败不产出成功文件。没有 FFmpeg 或中文字体时媒体集成测试会明确跳过，不能据此称为完整验证。

Web 测试另外覆盖 HTTP 角色库及本地素材完整性、媒体分段读取、路径边界、错误请求，以及实际导出 WAV 的时长与频率、1080p MP4 的帧率与音轨。

## 后续阶段

依次加入 AI 文案与分镜、B 站视频理解及运营、QQ 人格与私人记忆、Updream 游戏二创，最后由 AstrBot 插件统一管理并部署服务器。后续 AI 直接生成同一种项目配置，插件调用现有渲染入口。私人每日总结不进入公开文案和视频素材。

第一阶段没有连接模型、平台账号或发布服务。
