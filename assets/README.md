# 素材说明

`originals/` 保存用户提供的五张原图，复制时不修改文件内容：

| 文件 | 用途 |
| --- | --- |
| reference-layout.png | 完整版式参考；示例通过 crop 使用上方截图区域 |
| role-silver.jpg | 角色素材 |
| role-blue.jpg | 角色素材 |
| role-red.jpg | 角色素材 |
| role-red-expression.jpg | 表情/构图变体 |

这些 JPEG 自带蓝底，首版原样使用，蓝底色差及原图拼贴边缘会保留。引擎也支持真正带透明通道的 PNG。需要透明角色时另行制作遮罩，勿直接把所有蓝色像素删除。

`music/demo-original.wav` 是 `scripts/make_examples.py` 本地合成的原创测试音轨，仅用于演示音量、加速、升调和淡出，不是崩铁歌曲。真实音乐文件由项目的 `music.path` 指定。

Web 测试新增的 `characters/` 来自 [StarRailRes](https://github.com/Mar-7th/StarRailRes)，`catalog.json` 记录可搜索的 88 个具名角色及本地头像、半身图路径。`scripts/sync_characters.py` 可更新索引并补下载缺失图片。

`web/kobe-face.png` 从 `originals/role-red-expression.jpg` 的 `[263,174,147,171]` 像素区域提取，保留原图不动。前端将其裁成可调椭圆，并支持更换素材；它仍可能带有参考图中的少量头发或背景边缘，适合先测试拼贴流程。`icons/` 是 Lucide 的公开 SVG 图标，许可见同目录 LICENSE。

图片及其包含的角色、人物、界面素材权利归各自权利人。本项目不将参考作者的完整视频作为成片素材。

