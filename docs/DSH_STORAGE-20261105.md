# DSH桌宠缺包与存储迁移（2026-11-05）

## 当前结果

| 项目 | 实际状态 |
| --- | --- |
| DSH主数据 | `D:/DSHData`，原C盘`~/.dsh`是junction兼容入口，不设置第二份home |
| 数据校验 | 51,108文件、511目录链接、2,717,884,030字节；复制前后逐文件SHA256、目录项及链接目标一致 |
| 链接处理 | 510个junction保留目标，原指向`D:/Code/plugins/dsh-bili-whale`的目录symlink用等价junction承接，未复制外部目标内容 |
| 权限 | D盘home继承原home权限并保护继承；完整备份ZIP亦恢复原home访问权限 |
| npm缓存/pnpm store | 原npm缓存已经在`D:/npm-cache`；本轮pnpm使用`D:/pnpm-store`，安装临时文件在仓库D盘`.tools/dsh-install-tmp` |
| 桌宠包 | `dsh-pet 0.3.8`已补齐；实际入口为`D:/DSHData/profiles/desktop/node_modules/dsh-pet/lib/index.js`，bundle patch存在；不再是只有依赖声明 |
| 宿主 | 重启后Web已启动，控制层stage=done、8任务挂载，巡逻任务恢复Enabled；QQ仍未登录，非桌宠验收 |
| 显示验收 | Computer Use点击设置入口时Windows返回GetCursorPos拒绝访问，已停止输入；未确认桌宠显示效果 |
| C盘空间 | **尚未释放旧副本占用**；清理测试被自动安全审核拒绝，未执行生产删除或换工具重试删除 |

## 安装过程发现的阻塞

采用官方随包`dsh plugin --profile desktop`，退出宿主、暂停巡逻后操作，不改ASAR、不跳版本检查、不运行依赖生命周期脚本。

1. 原依赖目录需要重建，pnpm无TTY而中止；按CLI说明使用非交互环境继续。
2. 三条file依赖把源目录写成自身node_modules：`@liustack/modsearch`、`@loserfox/distill`、`dsh-fail-logger`。重建目录后源不存在，导致完整安装/回滚失败。原包已从迁移前副本保存到`D:/DSHData/plugin-sources/*.tgz`，原目录也已恢复。直接Python修改profile manifest遇到权限拒绝，未通过换Shell写该文件。
3. 原包归档版本为5.10.11、0.1.0、0.5.2，许可证和包内容沿用npm pack，不改实现。管理器remove/add事务仍被全局兼容检查拒绝并回滚manifest，所以**这三条自引用源尚未修正**，不能声称完整install已成功。
4. 当前DSH0.2.2-rc.1不接受旧`dsh-find-plugin@0.4.0`、`dsh-ops@0.4.4`及适配版`dsh-plugin-bilibili@0.2.4`的版本声明。核对npm当前latest后未找到可直接升级的对应兼容版本；没有执行allow-version、降级DSH或放宽插件声明。后续须独立做真实兼容适配并验证，再完成稳定安装源替换。

原`cordis.patch.yml`与迁移前副本逐字节一致。桌宠缺包问题与以上全局维护问题分开记录，不把文件存在当完整运行验收。

## 迁移前副本与C盘清理

- 原目录：`C:/Users/kongb/.dsh.before-D-20261105`，真实目录、非链接。
- D盘完整备份：`outputs/review-20261105/dsh-home-before-pet-20261105.zip`，约1.46GB；含51,108文件及511条目录链接元数据，所有条目CRC、原设置文件内容核对通过。SHA256记录在同目录`home-archive.json`。
- ZIP里`__dsh_directory_links__.json`保存链接目标；普通解压不自动重建这些junction，恢复时须据此恢复，不能把链接元数据当成实际包内容。
- 自动审核只给出`blocked by policy`，阻止了含递归清理测试的组合命令；未执行该命令，没有生产删除回执。之后仅单独恢复备份文件ACL，未继续执行删除。
- 本人可运行`outputs/review-20261105/cleanup-migrated-c-backup.cmd`。它调用同目录`cleanup-old-home.py --apply`，只针对上述固定C盘副本；先核对活动home的D盘junction、ZIP的SHA256和备份记录，再用Python3.12 shutil.rmtree删除旧副本。**助手只执行过--check，结果通过，没有执行--apply。**
- 清理后记录实际C盘可用空间变化；当前不能承诺已释放2.72GB，逻辑文件大小也不等于物理回收空间。

## 验证边界

复制0失败，迁移文件/链接校验一致，ZIP全条目CRC通过，包入口与bundle文件解析通过，宿主启动及控制层挂载通过。无收费模型/TTS测试，无QQ/B站/空间测试消息。UI、全局兼容修复、完整依赖重建和C盘清理均有上述明确限制。

参考：[官方DSH Desktop插件管理](https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/desktop/README.md)、[pnpm remove](https://github.com/pnpm/pnpm.io/blob/main/docs/cli/remove.md)、[Python3.12 shutil.rmtree的Windows junction行为](https://docs.python.org/3.12/library/shutil.html#shutil.rmtree)。
