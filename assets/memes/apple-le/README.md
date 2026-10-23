# 苹果乐、能天使与拉特兰表情

2026-10-23 从公开图片源收集，逐页检查后保留 **112 张**：苹果乐 4 张、能天使 50 张、拉特兰 58 张，其中 2 张为多帧动图。没有生成新图片；排除了无关人物、普通立绘、同一表白底图换角色的合集，以及重复上传。

`sources.json` 逐张记录原图地址、来源页、作者或水印线索、分类、尺寸、帧数和 SHA256。除了文件名，导入时保留原始字节；同时按解码后的像素去重，并检查缩略图近似重复。

来源包括 [Qsticker Archive](https://qsticker.akarin.dev/) 收录的 QQ 与 B 站公开表情包，以及公开的[能天使](https://ecywang.com/pic/%E8%83%BD%E5%A4%A9%E4%BD%BF%E8%A1%A8%E6%83%85%E5%8C%85/)与[莫斯提马](https://ecywang.com/pic/%E8%8E%AB%E6%96%AF%E6%8F%90%E9%A9%AC%E8%A1%A8%E6%83%85%E5%8C%85/)表情原图、Safebooru 的三张苹果乐相关梗图。原图水印和来源记录均保留。

图片存入本机 AstrBot 已启用的 `meme_manager/packs/builtin-default/memes/`，按上述三类保存，不把采集缓存放进插件。`outputs/meme-import-verification.json` 保存实际导入的完整性检查及插件扫描结果。

在 AstrBot 的 Python 环境中可按清单重新导入：

```powershell
D:\Code\Apps\AstrBot\.venv\Scripts\python.exe scripts/import_apple_memes.py --target D:/Code/Apps/AstrBot/data/plugin_data/meme_manager/packs/builtin-default
```

脚本会先检查全部图片，再写入资源包，并备份原有分类元数据。已有相同 SHA256 的图片会跳过。部署时可直接迁移该资源包；不必再次抓取。
