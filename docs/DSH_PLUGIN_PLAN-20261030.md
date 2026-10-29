# 插件安装方案（2026-10-30 凌晨拟定）

目标：把讨论过的 5 个社区插件装上，用于自进化（学技能/记错因）与省 token（余额、上下文审计），
并给"只读逛社区"准备浏览能力。

## 一、清单

| # | 包 | 仓库 | 许可 | 作用 | 需要编译 |
|---|---|---|---|---|---|
| 1 | `@loserfox/distill` | LoserFox/distill | BSD-3 | 每 N 条用户消息后台反省，写/更新 `SKILL.md`（Hermes 反省提示词的移植） | 否（lib 已提交） |
| 2 | `dsh-fail-logger` | Areium/dsh-fail-logger | MIT | 工具失败去重记入 `~/.dsh/skills/fail-log-guide/SKILL.md`，并向系统提示注入预防规则 | 否 |
| 3 | `@liustack/modsearch` | liustack/modsearch | MIT | 网页搜索 + `read_page` 单页抓取 + X 搜索，默认 Firecrawl 免费额度 | **是**（仓库只有源码，必须用 npm 包里的 `dist/`） |
| 4 | `dsh-context-doctor` | Zhenyu98/dsh-context-doctor | BSD-3 | 审计指令链/技能目录/工具 schema 的 token 成本，输入框旁面板 + `context_audit` 工具 | 否（含 client 预编译） |
| 5 | `dsh-balance-meter` | Ghost011118/dsh-balance-meter | BSD-3 | 输入框下方显示 DeepSeek 余额与本会话花费（master 分支） | 否（含 client 预编译） |

不装（理由）：
- 记忆类（`dsh-mneme` / `dsh-memento` / `dsh-memory-vault`）：已有 `data/memory.db` + MCP，重复。
- `dsh-vision-toolkit` / `modlens`：识图已通（`read_image` + `dsh-tool-fs`）。
- `dsh-browser`：权限面太大（可操控浏览器），只读用 modsearch 的 `read_page` 足够。
- PPT / 视频类：当前没有需求。

## 二、安装方式（绕开 `dsh plugin add` 的 SQLite 锁问题）

本机 `dsh plugin add` 会因为 pnpm store 在 `D:\pnpm-store` 拿不到锁而失败。走手动装：

```powershell
# 1) 备份
copy ~/.dsh/profiles/desktop/package.json  →  outputs/plugin-backup/package.json.<时间>
copy ~/.dsh/profiles/desktop/cordis.patch.yml → outputs/plugin-backup/cordis.patch.yml.<时间>

# 2) 暂存区取包（npm registry 包，含预编译产物）
$stage = D:\Code\Projects\FatFishLife\.tools\plugin-staging
npm pack @loserfox/distill dsh-fail-logger @liustack/modsearch dsh-context-doctor dsh-balance-meter --pack-destination $stage

# 3) 解压到 profile
tar -xzf <pkg>.tgz -C $stage/<name>       # 每个包一个目录
copy $stage/<name>/package → ~/.dsh/profiles/desktop/node_modules/<pkg-name>/

# 4) 依赖：balance-meter 需要 clsx
npm pack clsx  → 解压到 profile/node_modules/clsx

# 5) 写 package.json：dependencies + dsh.profile.bundles 追加五个名字（去重）
```

如果 npm registry 上没有某个包（例如 `dsh-context-doctor` 是 `private: true` 未发布），
退回 git 方式：`git clone` 后直接复制仓库里的 `lib/`（已核对：lib 与 `lib/client.js` 都已提交）。

## 三、风险与缓解（**必须先确认**）

| 插件 | 风险 | 缓解 |
|---|---|---|
| `dsh-fail-logger` | 向**所有会话**的 systemPrompt 注入三段预防规则（order 90/185/190），QQ 会话也会带上"用 run_code 调用工具"这类与社交场景无关的文字 | 安装后检查 QQ 会话的 system 长度；必要时设 `injectInstructions: false`，只保留失败实录 |
| `distill` | 每个会话 `turn-stopping` 都会评估，**包括 QQ 聊天**；`minUserMessages` 默认 3，可能频繁触发反省子代理（耗 token 并写技能） | 初始设 `minUserMessages: 10`、`targetRoot: 'user'`；观察一周再调 |
| `modsearch` | 给 agent 联网读任意 http(s) 页面的能力 | 先**不给 QQ 社交作用域**（群友可能滥用）；只在我这边会话可用 |
| 所有 | 组合层变更需要重启；装错会导致宿主起不来 | 全程备份；失败就删 bundles 项 + 包目录即可回滚 |

## 四、验证清单（重启后逐项）

| 项 | 怎么验证 | 通过标准 |
|---|---|---|
| 宿主启动 | 进程存在、GUI 能开 | 无 mount 报错 |
| distill | 聊 10 条以上，等后台反省 | `~/.agents/skills/*/SKILL.md` 出现带 `distilled-by: dsh-distill` 的文件 |
| fail-logger | 故意调一个会失败的工具（如读不存在的文件） | `~/.dsh/skills/fail-log-guide/SKILL.md` 出现 `FAIL-LOG:BEGIN/END` 段 |
| modsearch | 让我搜一条时效信息 | 返回带来源链接的结果 |
| context-doctor | 输入框右侧出现脉冲图标，点开有分片统计 | 显示指令链/技能/工具/MCP 四段 token |
| balance-meter | 输入框下方出现余额胶囊 | 显示余额与本场花费 |
| QQ 会话不受污染 | 读最新 QQ 会话的 system 长度与内容 | 不含 fail-logger 的 run_code 预防段（若含则关掉注入） |

## 四之二、贴吧 / 小黑盒（只读浏览）

这两家**没有独立插件**，能复用到的只有 modsearch 的 `read_page`。分三个层次，别混：

| 层次 | 含义 | 现在能不能 |
|---|---|---|
| L1 我这边的会话 | 我调 `read_page` 读页面，看完写摘要给她/你 | 装完 modsearch 就能 |
| L2 QQ 里的她 | 她在对话中自己调 `read_page` | 要给社交白名单放行，风险：群友能让她抓任意页面 |
| L3 她自己定时去逛 | 像 bili-whale 那样按作息自己逛、写日记 | **没有**，需要写一个执行器（类似 bili-whale 的调度+采集） |

可达性预判（需实测确认，不作断言）：

- **贴吧**：帖子页有服务端渲染正文，`read_page` 有较大概率能读到；需要登录的板块（部分吧、图片、楼中楼）读不到。
- **小黑盒**：内容基本在登录墙后，`read_page` 预计失败。若要读，只能挂 `dsh-browser` 用你已登录的浏览器——但它可点击任意页面，权限面远大于只读，不建议给 bot。

实测步骤（装完 modsearch 后执行，结果写回本文件）：

1. 取一个公开贴吧帖子的 URL，`read_page` 读，记录：是否返回正文、是否有标题、耗时。
2. 取一个小黑盒帖子 URL，同样记录。
3. 若贴吧可读、小黑盒不可读：贴吧进 L2（放行社交白名单），小黑盒停在 L1（我读给你）。

### 实测结果（2026-10-30 04:10，已执行）

| 目标 | 结果 | 原因 |
|---|---|---|
| 贴吧 `tieba.baidu.com/f?kw=明日方舟` | ❌ 403「百度安全验证」 | 反爬拦截，本地直连拿不到正文 |
| 小黑盒 `www.xiaoheihe.cn` | ❌ 200 但正文为空 | 内容由 JS 渲染，本地引擎不执行 JS |
| 云端引擎（Firecrawl keyless） | ❌ 403 | 提示"IP 看起来像 VPN/代理"，本机走代理，匿名额度被拒 |

结论：**当前状态下两家都读不到**。可行的下一步（需你决定）：

1. 申请一个免费 Firecrawl key（1000 credits/月），`modsearch config set firecrawl.apiKey <key>`——
   云端引擎会渲染 JS，**小黑盒与贴吧都有机会读到**，这是成本最低的一条路。
2. 或者挂 `dsh-browser` 用你已登录的浏览器（权限面大，不建议给 bot）。
3. 或者放弃这两家，只保留 B 站（已有 bili-whale）。

## 五、回滚

1. 从 `~/.dsh/profiles/desktop/package.json` 的 `dsh.profile.bundles` 删掉对应条目
2. 删除 `node_modules/<包名>` 目录
3. 恢复备份的 `package.json` / `cordis.patch.yml`（如有改动）
4. 重启

## 六、顺序

1. 备份 → 2. 取包解压 → 3. 写 package.json → 4. 校验 YAML/JSON → 5. 重启 → 6. 逐项验证 → 7. 处理 QQ 会话污染问题（如出现）
