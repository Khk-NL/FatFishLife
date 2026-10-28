# DSH适配与隔离验证

当前复用官方DSH 0.2.1-rc.3及`dsh-onebot-qq` 0.9.6（BSD-3-Clause）。不修改签名资源，不从npm安装旧版DSH内部包，也不使用版本豁免。

先准备固定上游并打包，再验隔离宿主：

```powershell
.\.tools\dsh-python\Scripts\python.exe -X utf8 scripts/prepare_dsh_onebot.py --pack
.\.tools\dsh-python\Scripts\python.exe -X utf8 scripts/dsh_native_smoke.py
```

准备脚本检查`upstream-lock.json`的完整SRI，对每处源码替换断言匹配次数。归档位于`.tools/dsh-vendor/adapted/`，与原始下载缓存分开，保留原LICENSE。安装来源使用归档的`file:`地址；链接外部源码目录可能让宿主回退或插件自身依赖解析不到。

测试脚本只修改`outputs/dsh-migration/native-smoke`：新数据根、假账号、随机测试鉴权、仅loopback通信。它验证实际DSH加载、模拟OneBot回执、工作时段零模型调度、非主人后台命令隔离，以及真实Agent作用域中的工具body拦截。普通聊天调度当前使用计数替身，尚未证明完整模型请求和人格效果。结束时只终止本次启动的进程树。

报告与原始日志均在Git忽略目录；原始日志可能包含一次性测试Web UI登录地址，不贴到聊天或提交。失败时脚本返回非零；`ok=true`还须实际观察桥监听启动，不能只看测试模块能导入。

策略与适配回归：

```powershell
node --test dsh/tests/*.test.mjs
.\.tools\dsh-python\Scripts\python.exe -X utf8 -m unittest discover -s tests -p "test_dsh_*.py"
```

生产安装在P5另行处理：先完成模型/媒体/业务权限验证，完整退出DSH、备份profile，才显式运行安装器的`-IncludeQqBridge`。当前生产MCP仍声明旧记忆库，仓库模板已改到项目data；需按迁移文档核对最后增量，不能直接覆盖正在增长的库。
