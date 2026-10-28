# DSH适配与隔离验证

当前复用官方DSH 0.2.1-rc.3及`dsh-onebot-qq` 0.9.6（BSD-3-Clause）。不修改签名资源，不从npm安装旧版DSH内部包，也不使用版本豁免。

先准备固定上游并打包，再验隔离宿主：

```powershell
.\.tools\dsh-python\Scripts\python.exe -X utf8 scripts/prepare_dsh_control.py
.\.tools\dsh-python\Scripts\python.exe -X utf8 scripts/prepare_dsh_onebot.py --pack
.\.tools\dsh-python\Scripts\python.exe -X utf8 scripts/dsh_native_smoke.py
```

准备脚本检查`upstream-lock.json`的完整SRI，对每处源码替换断言匹配次数。归档位于`.tools/dsh-vendor/adapted/`，与原始下载缓存分开，保留原LICENSE。文件名带归档哈希，`*-current.json`记录当前路径和完整哈希，避免同名tarball被pnpm锁缓存复用旧代码。安装来源使用归档的`file:`地址；链接外部源码目录可能让宿主回退或插件自身依赖解析不到。QQ桥依赖管理插件提供的`fatfishSettings`，测试脚本会先装管理插件。

测试脚本只修改`outputs/dsh-migration/native-smoke`：新数据根、假账号、随机测试鉴权、仅loopback通信。它验证实际DSH加载、模拟OneBot回执、工作时段零模型调度、非主人后台命令隔离，以及真实Agent作用域中的工具body拦截。普通聊天调度当前使用计数替身，尚未证明完整模型请求和人格效果。结束时只终止本次启动的进程树。

报告与原始日志均在Git忽略目录；原始日志可能包含一次性测试Web UI登录地址，不贴到聊天或提交。失败时脚本返回非零；`ok=true`还须实际观察桥监听启动，不能只看测试模块能导入。

策略与适配回归：

```powershell
node --test dsh/tests/*.test.mjs
.\.tools\dsh-python\Scripts\python.exe -X utf8 -m unittest discover -s tests -p "test_dsh_*.py"
```

生产安装在P5另行处理：先完成模型/媒体/业务权限验证，完整退出DSH、备份profile，才显式运行安装器的`-IncludeQqBridge`。当前生产MCP仍声明旧记忆库，仓库模板已改到项目data；需按迁移文档核对最后增量，不能直接覆盖正在增长的库。

## 白盒管理插件

`dsh/control`是原生宿主插件`dsh-fatfish-life`，提供中文元信息、Config schema和`fatfish_status`管理工具。控制项包括身份、静默、触发词、冷却、上海时间的忙碌窗口、语音/表情概率、运营开关和计划时间。默认周末也按忙碌窗口处理；可选星期和跨午夜窗口，返回时间按实际结束点生成。

先审查安装动作：

```powershell
.\.tools\dsh-python\Scripts\python.exe -X utf8 scripts/dsh_install_control.py --dry-run
```

完全退出DSH后，运行同一命令去掉`--dry-run`。它备份原profile文件、通过随桌面CLI安装本地包，只新增控制行，不接NapCat、不停止AstrBot、不覆盖其他patch或已有管理参数。启动后应在原生插件页查找“FatFishLife 管理”；实际桌面点击/保存仍需现场验收。权威配置由DSH保存，插件生成`data/dsh/runtime-policy.json`和`runtime-behavior.json`供适配层使用，MCP决策会读回更新并保留遗漏次数。

当前运营工作流只保存目标计划，执行器尚未注册；媒体最终投递也未挂生产。界面描述和`fatfish_status`均保留这些限制，不能把“文件已写出”当成“已在QQ生效”。

## 可选配音服务

保持原语音概率15%；可选`siliconflow`、`elevenlabs`、`minimax`，每家单独设置模型、音色ID、语速和接口地址。默认保留现用硅基音色；不同服务的音色ID不能直接复用。`allowSynthesis`默认关闭，明确开启才授权可能收费的TTS，不会同时打开记忆写入或公开发布权限。

ElevenLabs凭据从本机文件引用，不写进插件配置或Git：

```powershell
.\.tools\dsh-python\Scripts\python.exe -X utf8 scripts/dsh_elevenlabs_check.py --env-file "C:\Users\kongb\Desktop\.env"
```

该检查只读取模型和音色列表，不合成、不消耗TTS字符；本机缓存供配置schema显示音色/模型选项，更新列表后需重载插件。已验证本账户9模型、21音色；真实配音与QQ播放尚未验收。MiniMax读取`MINIMAX_API_KEY`或`FATFISH_MINIMAX_API_KEY`，ElevenLabs读取自己的专用变量/文件，不借用DeepSeek或硅基密钥。

接口依据：[ElevenLabs合成](https://elevenlabs.io/docs/api-reference/text-to-speech/convert)、[音色列表](https://elevenlabs.io/docs/api-reference/voices/search)、[MiniMax同步合成](https://platform.minimax.io/docs/api-reference/speech-t2a-http)。当前是薄REST适配，继续复用同一MCP、概率与音频规整出口；无需另装一套语音Agent。
