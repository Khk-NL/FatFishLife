# DSH 插件对齐与升级验收

日常 desktop 在 2026-11-20 切到随包的 DSH 0.2.2-rc.5 SDK。旧 `profiles/node_modules/@deepseek-ai` 的 rc.1 junction 已同目录改名保留，原目标目录没有改动。FatFish 控制层沿用目前安装的实现，只把精确 rc.1 peer 改成与官方 `engines.dsh` 相同的受限区间；超出此区间由官方兼容门禁处理，从未设置版本豁免。保持用户的 `autoInstallPeers: false`。不要为未来版本重新复制 SDK 或打开自动安装 peer。

## 升级前后如何查

```powershell
python scripts/dsh_sdk_preflight.py
```

脚本以安装包内的 SDK 和日常插件清单为准，检查缺包、按官方规则拒载的 bundle、两层本机 SDK 版本冲突；不运行插件、不读凭据、不联网。输出为 JSON；退出码 0 表示静态检查通过，1 表示发现差异，2 表示不能完成检查。官方安装目录布局若变化，检查会明确失败，不默许新版本。静态检查通过后，再让新版原生宿主验收关键组合；只有同一宿主里的实测才能证明工具生效。

## 当前验收与回退

- 安装器保留 35 个 bundle 的加载顺序及其余依赖，三个原已停用的插件未启用。两套预设只新增 MCP 使用规则，其他 YAML 字段未变。
- 隔离 Web 宿主复用现有七个插件：FatFish、微信、DrawAI、tool-gate、工具管理、OPS 和 dsh-context；实读宿主工具 SDK 为 rc.5，FatFish 应用设置并注册 `fatfish_status`，DrawAI 和门禁工具能发现，微信启动但没有绑定测试账号。OPS 的逐步工具选择沿用用户此前实机回执，本轮合装未调用。
- 日常重启后控制层挂载完成，心跳与微信状态刷新；检查时没有新增崩溃报告。未付费、未主动进行平台写入，原 QQ 暂停标记与官方账号关闭状态保留。
- 私有备份在 `outputs/dsh-migration/rc5-alignment-20261120-024735-912/`。若需回退，先正常退出 DSH；根据 `rollback-map.json` 恢复旧 junction 的名字；用官方插件管理器重装备份 package.json 记录的原控制包；必要时只恢复同批确认过的 profile 文件。已有新设置时先比较再回退，避免覆盖用户编辑。
