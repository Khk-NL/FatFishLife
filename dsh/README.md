# DSH适配与隔离验证

当前复用官方DSH 0.2.1-rc.3及`dsh-onebot-qq` 0.9.6（BSD-3-Clause）。不修改签名资源，不从npm安装旧版DSH内部包，也不使用版本豁免。

先准备固定上游并打包，再验隔离宿主：

```powershell
.\.tools\dsh-python\Scripts\python.exe -X utf8 scripts/prepare_dsh_control.py
.\.tools\dsh-python\Scripts\python.exe -X utf8 scripts/prepare_dsh_onebot.py --pack
.\.tools\dsh-python\Scripts\python.exe -X utf8 scripts/dsh_native_smoke.py
```

准备脚本检查`upstream-lock.json`的完整SRI，对每处源码替换断言匹配次数。归档位于`.tools/dsh-vendor/adapted/`，与原始下载缓存分开，保留原LICENSE。文件名带归档哈希，`*-current.json`记录当前路径和完整哈希，避免同名tarball被pnpm锁缓存复用旧代码。安装来源使用归档的`file:`地址；链接外部源码目录可能让宿主回退或插件自身依赖解析不到。QQ桥依赖管理插件提供的`fatfishSettings`，测试脚本会先装管理插件。

测试脚本只修改`outputs/dsh-migration/native-smoke`：新数据根、假账号、随机测试鉴权、仅loopback通信。基础策略用计数替身，普通聊天另恢复真实dispatch，使用官方LlmAdapter的纯本地mock验证真实Agent创建、完整2096字人格请求及最终回复回执。当前14项原生检查包含生成中静默/进入工作窗口、402不外泄、人格挂载失败零模型调用。它不验证云端/本地真实模型的口吻质量，不合成音频、不发真实QQ。结束时只终止本次启动的进程树。

P1社交作用域不注册未开放的QQ工具。`restrict({allow:[]})`只能过滤继承面，无法隐藏同作用域自己注册的工具；guard仍为执行前校验。原始桥把7个QQ工具与编程/管理命令说明写进模型提示，现已在准备脚本中收回。后续通过审查的媒体能力接宿主出口，不能直接恢复raw NapCat、跨目标或私库工具。人格预设挂载失败直接终止会话创建，不降级成通用Agent。

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

完全退出DSH后，运行同一命令去掉`--dry-run`。它备份原profile文件、通过随桌面CLI安装本地包，只新增控制行，不接NapCat、不停止AstrBot、不覆盖其他patch或已有管理参数。2026-10-28已获用户授权装入日常desktop并重启，原生插件页已看见“FatFishLife 管理”运行。回复、时间段、媒体和工作流分组采用DSH volatile表单；保存监听更新同一服务与生效版本。身份/目录需通过配置文件修改。权威配置由DSH保存，插件生成`data/dsh/runtime-policy.json`和`runtime-behavior.json`供适配层使用，MCP决策会读回更新并保留遗漏次数。

原生宿主已验证保存15→16→15与缓存同步；最后桌面鼠标保存因电脑工具拒绝访问尚未验收，安装、加载与原生保存证据分开记录。默认静默、语音15%、表情35%、收费合成关闭。

管理包现包含原生客户端`client.js`。`volatile`只让Settings提供配置数据，实际编辑入口由此客户端注册到插件页的`plugins.item`插槽；中文卡片目标名为“FatFishLife 管理”。编辑后点“保存参数”，通过ConfigForms写回DSH；并发冲突保留草稿，点“放弃修改”读回当前值。时间窗口支持增删及星期选择，配音服务可选三家。凭据只配置本机文件路径，不能把API key填进模型/音色字段。

新客户端已安装日常desktop；4项离线交互契约和15项原生宿主检查通过，实际桌面新卡片渲染/鼠标保存尚未验收。最终验收可临时把群聊冷却10改11保存，核对`runtime-policy.json`为11000ms，再恢复10并核对10000ms；保持静默与概率不变，无需发送平台消息或调用模型。

当前运营工作流只保存目标计划，执行器尚未注册；媒体最终投递也未挂生产。界面描述和`fatfish_status`均保留这些限制，不能把“文件已写出”当成“已在QQ生效”。

## 已安装的社区补充插件

- [moxingovo/dsh-bilibili](https://github.com/moxingovo/dsh-bilibili) 0.2.4：只保留`bilibili_search`、`bilibili_video`、`bilibili_subtitles`；不会注册抽帧/直链工具，不打包相关视频技能。
- [awesome-dsh-plugin/dsh-find-plugin](https://github.com/awesome-dsh-plugin/dsh-find-plugin) 0.4.0：联网发现插件，限流时明确降级；安装提示指向desktop。搜索结果不会自动执行。
- 原知识库0.1.5、Obsidian0.2.6保留。bili-cli0.6.0已在本机，继续服务已有账号业务，不重复安装或重置登录。

固定提交与MIT许可见`upstream-lock.json`；`prepare_dsh_community.py`使用上游提交的构建产物，不执行安装/构建脚本，保留LICENSE。需复装时先完全退出DSH，再运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dsh_install_plugins.ps1 -IncludeCommunity
```

只验证插件原生加载与公开读取（无收费模型/TTS、无平台写入）：

```powershell
.\.tools\dsh-python\Scripts\python.exe scripts/prepare_dsh_control.py
.\.tools\dsh-python\Scripts\python.exe scripts/prepare_dsh_onebot.py --pack
.\.tools\dsh-python\Scripts\python.exe scripts/prepare_dsh_community.py
.\.tools\dsh-python\Scripts\python.exe scripts/dsh_native_smoke.py --community
```

插件工坊1.6.2多处写死`profiles/web`及`--profile web`，当前暂不安装，避免误改另一个profile。原生插件安装管理仍用DSH自带入口；不增加第二套定时器、记忆或语音Agent。

## 可选配音服务

保持原语音概率15%；可选`siliconflow`、`elevenlabs`、`minimax`，每家单独设置模型、音色ID、语速和接口地址。默认保留现用硅基音色；不同服务的音色ID不能直接复用。`allowSynthesis`默认关闭，明确开启才授权可能收费的TTS，不会同时打开记忆写入或公开发布权限。

ElevenLabs凭据从本机文件引用，不写进插件配置或Git：

```powershell
.\.tools\dsh-python\Scripts\python.exe -X utf8 scripts/dsh_elevenlabs_check.py --env-file "C:\Users\kongb\Desktop\.env"
```

该检查只读取模型和音色列表，不合成、不消耗TTS字符；本机缓存供配置schema显示音色/模型选项，更新列表后需重载插件。已验证本账户9模型、21音色；真实配音与QQ播放尚未验收。MiniMax读取`MINIMAX_API_KEY`或`FATFISH_MINIMAX_API_KEY`，ElevenLabs读取自己的专用变量/文件，不借用DeepSeek或硅基密钥。

接口依据：[ElevenLabs合成](https://elevenlabs.io/docs/api-reference/text-to-speech/convert)、[音色列表](https://elevenlabs.io/docs/api-reference/voices/search)、[MiniMax同步合成](https://platform.minimax.io/docs/api-reference/speech-t2a-http)。当前是薄REST适配，继续复用同一MCP、概率与音频规整出口；无需另装一套语音Agent。
