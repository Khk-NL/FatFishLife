"""把定时业务执行器、主动开口与中枢调用接进 fatfish-control（一次性脚本）。

用精确字符串替换 + 断言，替换失败就整体不动，避免改坏正在跑的插件。
"""
from pathlib import Path

TARGET = Path(r"D:\Code\Projects\FatFishLife\dsh\control\index.mjs")
source = TARGET.read_text(encoding="utf-8")
original = source


def replace(old: str, new: str, count: int = 1) -> None:
    global source
    found = source.count(old)
    if found != count:
        raise SystemExit(f"锚点出现 {found} 次（期望 {count}）：{old[:60]!r}")
    source = source.replace(old, new)


# ── 1. 导入 ─────────────────────────────────────────────────
replace(
    "import { dueTasks, nextRun, readState, writeState } from './schedule.mjs';\nimport { existsSync, readFileSync } from 'node:fs';",
    """import { TASKS, dueTasks, nextRun, readState, writeState } from './schedule.mjs';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { runTask } from './business.mjs';
import { runProactive } from './proactive.mjs';
import { sendText } from './transport.mjs';
import { chat as llmChat } from './llm.mjs';
import * as bili from './bili.mjs';
import * as hub from './hub.mjs';""",
)

# ── 2. 配置字段 ─────────────────────────────────────────────
replace(
    "  }).default({}).description('运营执行器尚未注册：这里保存目标计划，当前不会据此自动发动态、评论或定时消息'),\n});",
    """  }).default({}).description('运营计划：定时触发器在跑，发送与写回由 runner 决定'),
  tasks: z.array(z.object({
    id: z.string().required(),
    kind: z.string().required().description('bili-recommend / bili-inbox / bili-study / diary'),
    at: time().required(),
    enabled: z.boolean().default(true),
    label: z.string().default(''),
  })).default(TASKS).description('定时任务表；改时间只改这里，不用改代码'),
  runner: z.object({
    enabled: z.boolean().default(true).description('总开关：关掉后定时任务只记录不执行'),
    ownerChat: z.string().default('').description('主人私聊会话，如 private:3124904460；留空则用 identity.ownerId'),
    groupChats: z.array(z.string()).default([]).description('同时发到哪些群，如 group:1027577412；默认不发群'),
    biliBin: z.string().default('D:/Code/Apps/bili-venv/Scripts/bili.exe'),
    python: z.string().default('D:/Code/Projects/FatFishLife/.tools/dsh-python/Scripts/python.exe'),
    hubCli: z.string().default('D:/Code/Projects/FatFishLife/dsh/service/fatfish_hub_cli.py'),
    diaryDir: z.string().default('D:/obsidian/vaults/SCSldr/Journal').description('日记写进哪个 Obsidian 目录；留空不写文件'),
    diaryToOwner: z.boolean().default(true).description('日记写好后给主人发一小段摘要'),
    model: z.string().default('deepseek-chat'),
  }).default({}),
  proactive: z.object({
    enabled: z.boolean().default(true).description('主动开口总开关；忙时、深夜、超间隔与日上限都还会拦'),
    basePercent: percent(8).description('每 5 分钟检查一次时开口的基础概率，单位%'),
    minGapMinutes: z.number().min(5).default(150).description('两次主动开口的最小间隔（分钟）'),
    dailyCap: z.number().min(1).default(3).description('每天最多主动说几次'),
    quietStart: time().default('00:30'),
    quietEnd: time().default('07:30'),
    maxChars: z.number().min(10).default(60),
  }).default({}),
});""",
)

# ── 3. 可在 UI 编辑的字段 ────────────────────────────────────
replace(
    "const liveFields = ['reply', 'busyWindows', 'voice', 'meme', 'workflows'];",
    "const liveFields = ['reply', 'busyWindows', 'voice', 'meme', 'workflows', 'tasks', 'runner', 'proactive'];",
)

# ── 4. 状态描述 ────────────────────────────────────────────
replace(
    """  const status = { appliedRevision: compiled.revision, appliedAt: new Date().toISOString(),
    policy: '运行缓存已写入；QQ接入时从此服务读取', media: '概率参数已导出，生产媒体出口未完成',
    workflows: '目标计划已保存；定时触发器在跑，但业务出口（推荐/学习/日记）尚未接入',
    schedule: { executor: '每 30 秒检查一次（进程内定时器，不用系统 cron）', lastDue: null, next: null },
    productionCutover: false };""",
    """  const status = { appliedRevision: compiled.revision, appliedAt: new Date().toISOString(),
    policy: '运行缓存已写入；QQ接入时从此服务读取', media: '概率参数已导出，生产媒体出口未完成',
    workflows: '定时任务已接执行器：B站推荐/收件箱/标签学习/日记，结果见 schedule.results',
    schedule: { executor: '每 30 秒检查一次（进程内定时器，不用系统 cron）', lastDue: null, next: null,
      results: {}, failures: {} },
    proactive: { executor: '每 5 分钟按概率判断一次', lastAt: null, lastResult: null, count: 0 },
    productionCutover: false };""",
)

# ── 5. 执行器本体 ───────────────────────────────────────────
OLD_BLOCK = """  // 定时触发层：判断交给 schedule.mjs（12 项测试），这里只负责"到点就叫"。
  // 现在到点只记录 + 更新状态，不调用任何业务 —— 业务出口（B站推荐、标签学习、
  // 日记生成）还没接，不能让它看起来像已经会自己干活。
  const scheduleDir = String(config.dataDirectory ?? 'D:/Code/Projects/FatFishLife/data/dsh')
  const runDue = (now = new Date()) => {
    try {
      const state = readState(scheduleDir)
      const due = dueTasks(now, { lastRun: state.lastRun ?? {} })
      if (due.length) {
        const lastRun = { ...(state.lastRun ?? {}) }
        for (const item of due) {
          lastRun[item.id] = now.toISOString()
          status.schedule.lastDue = { id: item.id, scheduledFor: item.scheduledFor, lateMinutes: item.lateMinutes, recordedAt: now.toISOString() }
          ctx.logger.info(`[fatfish] 定时任务到点 ${item.id}（迟到 ${item.lateMinutes} 分钟）；业务未接，仅记录触发`)
        }
        writeState(scheduleDir, { ...state, lastRun })
      }
      const next = nextRun(now)
      status.schedule.next = next ? { id: next.id, at: next.at, when: next.when.toISOString() } : null
    } catch (error) {
      ctx.logger.warn('[fatfish] 定时检查失败：' + (error?.message ?? String(error)))
    }
  }
  ctx.effect(() => {
    runDue()
    const timer = setInterval(runDue, 30_000)
    if (typeof timer.unref === 'function') timer.unref()
    return () => clearInterval(timer)
  })"""

NEW_BLOCK = """  // 定时触发层：判断交给 schedule.mjs（纯函数、有测试），这里负责真执行。
  // 某个任务失败不会影响其它任务；结果写进 schedule-state.json 的 results，
  // 状态卡上能看到「上次跑了什么、成没成」，不用翻日志。
  const scheduleDir = String(config.dataDirectory ?? 'D:/Code/Projects/FatFishLife/data/dsh')
  const proactiveFile = join(scheduleDir, 'proactive-state.json')
  const readJson = (file) => { try { return JSON.parse(readFileSync(file, 'utf8')) } catch { return {} } }
  const writeJson = (file, value) => {
    mkdirSync(dirname(file), { recursive: true })
    writeFileSync(file, JSON.stringify(value, null, 2) + '\\n')
  }
  const ownerChatOf = () => {
    const configured = String(config.runner?.ownerChat ?? '').trim()
    if (configured) return configured
    const ownerId = String(config.identity?.ownerId ?? '').trim()
    return ownerId ? 'private:' + ownerId : ''
  }
  const depsOf = (now) => {
    const live = snapshot()
    const runner = live.runner ?? {}
    const liveConfig = { ...live, dataDirectory: config.dataDirectory,
      runner: { ...runner, ownerChat: ownerChatOf() } }
    const hubOptions = { python: runner.python, cli: runner.hubCli }
    const state = readJson(join(scheduleDir, 'task-state.json'))
    return { ctx, config: liveConfig, now, state,
      log: (message) => ctx.logger.info(message),
      send: (chatId, text) => sendText(ctx, chatId, text, (m) => ctx.logger.warn(m)),
      bili: { recommend: (options) => bili.feedRecommend({ ...options, bin: runner.biliBin }), inbox: (options) => bili.feedInbox({ ...options, bin: runner.biliBin }) },
      llm: { chat: (messages, options) => llmChat(messages, { ...options, model: runner.model }) },
      hub: { moodGet: () => hub.moodGet(hubOptions), journalWrite: (day, content, source) => hub.journalWrite(day, content, source, hubOptions),
        journalRecent: (options) => hub.journalRecent({ ...hubOptions, ...options }), dayDigest: (day) => hub.dayDigest(day, hubOptions),
        styleTerms: (options) => hub.styleTerms({ ...hubOptions, ...options }) } }
  }
  const saveTaskState = (next) => writeJson(join(scheduleDir, 'task-state.json'), next)
  let running = false
  const runDue = async (now = new Date()) => {
    if (running) return
    running = true
    try {
      const state = readState(scheduleDir)
      const tasks = (config.tasks ?? TASKS).filter((task) => task.enabled !== false)
      const due = dueTasks(now, { lastRun: state.lastRun ?? {}, tasks })
      const lastRun = { ...(state.lastRun ?? {}) }
      const results = { ...(state.results ?? {}) }
      const failures = { ...(state.failures ?? {}) }
      for (const item of due) {
        const task = tasks.find((row) => row.id === item.id) ?? item
        lastRun[item.id] = now.toISOString()
        status.schedule.lastDue = { id: item.id, scheduledFor: item.scheduledFor, lateMinutes: item.lateMinutes, at: now.toISOString() }
        if (config.runner?.enabled === false) {
          results[item.id] = { at: now.toISOString(), ok: false, reason: 'runner-disabled' }
          ctx.logger.info(`[fatfish] ${item.id} 到点但执行器关闭，仅记录`)
          continue
        }
        ctx.logger.info(`[fatfish] ${item.id} 开始执行（迟到 ${item.lateMinutes} 分钟）`)
        let outcome
        try {
          outcome = await runTask(task, depsOf(now))
        } catch (error) {
          outcome = { ok: false, reason: error?.message ?? String(error) }
        }
        results[item.id] = { at: now.toISOString(), ok: outcome?.ok === true, sent: outcome?.sent ?? 0,
          reason: outcome?.reason, detail: outcome?.picked ?? outcome?.learned ?? outcome?.day ?? outcome?.count }
        if (outcome?.ok !== true) failures[item.id] = results[item.id]
        else delete failures[item.id]
        ctx.logger.info(`[fatfish] ${item.id} 结束：${outcome?.ok === true ? '成功' : '失败'}${outcome?.sent ? '，发出 ' + outcome.sent + ' 条' : ''}`)
      }
      // 学习到的标签单独存一份，供后续注入层读取（当前只是记录，不注入）
      writeState(scheduleDir, { ...readState(scheduleDir), lastRun, results, failures })
      status.schedule.results = results
      status.schedule.failures = failures
      const next = nextRun(now, tasks)
      status.schedule.next = next ? { id: next.id, at: next.at, when: next.when.toISOString() } : null
    } catch (error) {
      ctx.logger.warn('[fatfish] 定时检查失败：' + (error?.message ?? String(error)))
    } finally {
      running = false
    }
  }
  ctx.effect(() => {
    void runDue()
    const timer = setInterval(() => { void runDue() }, 30_000)
    if (typeof timer.unref === 'function') timer.unref()
    return () => clearInterval(timer)
  })

  // 主动开口层：每 5 分钟判断一次；真正发不发由 proactive.shouldSpeak 决定
  let proactiveRunning = false
  const tickProactive = async (now = new Date()) => {
    if (proactiveRunning) return
    if (config.runner?.enabled === false) return
    proactiveRunning = true
    try {
      const state = readJson(proactiveFile)
      const deps = depsOf(now)
      const outcome = await runProactive({ ...deps, busyWindows: snapshot().busyWindows ?? DEFAULT_WINDOWS,
        config: deps.config, state, saveState: async (next) => writeJson(proactiveFile, next) })
      status.proactive.lastAt = now.toISOString()
      status.proactive.lastResult = outcome.spoke === true ? { spoke: true, at: now.toISOString() } : { spoke: false, reason: outcome.reason }
      status.proactive.count = outcome.count ?? state.count ?? 0
      if (outcome.spoke) ctx.logger.info('[fatfish] 主动开口成功')
      else if (outcome.ok === false) ctx.logger.warn('[fatfish] 主动开口未完成：' + (outcome.reason ?? 'unknown'))
    } catch (error) {
      ctx.logger.warn('[fatfish] 主动开口异常：' + (error?.message ?? String(error)))
    } finally {
      proactiveRunning = false
    }
  }
  ctx.effect(() => {
    const timer = setInterval(() => { void tickProactive() }, 5 * 60_000)
    if (typeof timer.unref === 'function') timer.unref()
    return () => clearInterval(timer)
  })"""

replace(OLD_BLOCK, NEW_BLOCK)

# ── 6. 状态工具暴露更多信息 ──────────────────────────────────
replace(
    """    execute: async () => { await pending; const current = snapshot(); return { ...status,
      busyWindows: current.busyWindows, voice: current.voice, meme: current.meme, workflows: current.workflows }; } }));""",
    """    execute: async () => { await pending; const current = snapshot(); return { ...status,
      busyWindows: current.busyWindows, voice: current.voice, meme: current.meme, workflows: current.workflows,
      tasks: current.tasks, runner: { ...current.runner, ownerChat: ownerChatOf() }, proactive: current.proactive }; } }));""",
)

replace(
    "  ctx.logger.info('FatFish配置已应用，版本 ' + compiled.revision.slice(0, 12) + '；运营执行器仍待接入');",
    "  ctx.logger.info('FatFish配置已应用，版本 ' + compiled.revision.slice(0, 12) + '；定时业务与主动开口已接入');",
)

TARGET.write_text(source, encoding="utf-8", newline="\n")
print("patched", len(source) - len(original), "chars")
