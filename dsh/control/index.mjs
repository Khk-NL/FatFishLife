import z from '@deepseek-ai/schemastery';
import { defineTool } from '@deepseek-ai/dsh-tools';
import { DEFAULT_WINDOWS, persistSettings } from './settings.mjs';
import { TASKS, dueTasks, nextRun, readState, writeState } from './schedule.mjs';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { runTask } from './business.mjs';
import { runProactive } from './proactive.mjs';
import { sendText } from './transport.mjs';
import { chat as llmChat } from './llm.mjs';
import * as bili from './bili.mjs';
import * as hub from './hub.mjs';

export const name = 'fatfish-control';
export const inject = ['tools'];
const time = () => z.string().pattern(/^(?:[01]\d|2[0-3]):[0-5]\d$/);
const percent = value => z.number().min(0).max(100).default(value);
const seconds = value => z.number().min(0).default(value);
const catalogFile = 'D:/Code/Projects/FatFishLife/data/dsh/elevenlabs-catalog.json';
const catalog = existsSync(catalogFile) ? JSON.parse(readFileSync(catalogFile, 'utf8')) : {};
const elevenVoice = () => catalog.voices?.length
  ? z.union([z.const('').description('请选择音色'), ...catalog.voices.map(row => z.const(row.id).description(row.name))]).default('')
  : z.string().default('').description('音色ID；只读获取音色列表后重载插件可选择音色');
const elevenModel = () => catalog.models?.length
  ? z.union(catalog.models.map(row => z.const(row.id).description(row.name))).default('eleven_multilingual_v2')
  : z.string().default('eleven_multilingual_v2');
export const Config = z.object({
  dataDirectory: z.string().default('D:/Code/Projects/FatFishLife/data/dsh').description('生效缓存目录；权威配置由DSH保存，此目录文件由插件生成'),
  identity: z.object({ adapterId: z.string().default('napcat-main'), botId: z.string().pattern(/^[1-9][0-9]*$/).required(),
    ownerId: z.string().pattern(/^[1-9][0-9]*$/).required() }).description('可信身份：QQ号由传输层验证，称呼与群管理员身份不授予后台权限'),
  reply: z.object({ silent: z.boolean().default(true).description('全局静默：只收不发'),
    busyText: z.string().default('拉特兰通讯现在是峰时收费，{hour}点再聊').description('忙时那句固定文案；{hour} 会替换成 12 或 18'),
    groupCooldownSeconds: seconds(10), userCooldownSeconds: seconds(60), dedupSeconds: seconds(300),
    normalKeywords: z.array(z.string()).default(['苹果派', '啊噗噜派']).description('正常时段附加触发词，忙碌时全部失效') }).default({}),
  busyWindows: z.array(z.object({ start: time().required(), end: time().required(),
    weekdays: z.array(z.number().step(1).min(0).max(6)).default([0,1,2,3,4,5,6]).description('0为周日，6为周六') }))
    .default(DEFAULT_WINDOWS).description('上海时间；默认每天生效。忙时仅真@、戳本人、正文苹果乐触发固定回复，零模型/语音'),
  voice: z.object({ enabled: z.boolean().default(true), basePercent: percent(15).description('基础概率，单位%'), stepPercent: percent(0), maxPercent: percent(100),
    allowSynthesis: z.boolean().default(false).description('明确允许可能收费的合成；迁移联验前保持关闭。此开关不授权记忆或公开发布写入'),
    provider: z.union([z.const('siliconflow').description('硅基流动（现用）'), z.const('elevenlabs').description('ElevenLabs'), z.const('minimax').description('MiniMax')]).default('siliconflow').description('切换合成服务，不改变发送概率；不同服务的音色ID不可复用'),
    providers: z.object({
      siliconflow: z.object({ apiBase: z.string().default('https://api.siliconflow.cn/v1'), modelId: z.string().default('FunAudioLLM/CosyVoice2-0.5B'),
        voiceId: z.string().default('').description('留空沿用本机FATFISH_TTS_VOICE，不改变现用克隆音色'), speed: z.number().min(.25).max(4).default(1.1) }).default({}),
      elevenlabs: z.object({ apiBase: z.string().default('https://api.elevenlabs.io/v1'), modelId: elevenModel().description('只读接口列出的账户可用模型；具体中文表现需要试听比较'),
        voiceId: elevenVoice(), speed: z.number().min(.7).max(1.2).default(1),
        envFile: z.string().default('C:/Users/kongb/Desktop/.env').description('只保存密钥文件路径，密钥不进入DSH配置或聊天') }).default({}),
      minimax: z.object({ apiBase: z.string().default('https://api.minimax.io/v1'), modelId: z.string().default('speech-2.8-hd'),
        voiceId: z.string().default(''), speed: z.number().min(.5).max(2).default(1),
        envFile: z.string().default('').description('使用MINIMAX_API_KEY或FATFISH_MINIMAX_API_KEY，不借用其他服务密钥') }).default({}),
    }).default({}),
    cooldownSeconds: seconds(0).description('当前原生TTS无冷却，0保持现状'), maxTextLength: z.number().min(0).step(1).default(0).description('0不额外限长'),
    manualTrigger: z.boolean().default(false), textAlongsideVoice: z.boolean().default(false) }).default({}).description('已接概率决策；QQ最终媒体出口待联验'),
  meme: z.object({ enabled: z.boolean().default(true), basePercent: percent(35), stepPercent: percent(10).description('未实际发出后增加的百分点'),
    maxPercent: percent(90), manualTrigger: z.boolean().default(true), maxPerMessage: z.number().step(1).min(1).max(9).default(1) })
    .default({}).description('以实际发送回执重置概率，选中素材不算发送成功'),
  workflows: z.object({
    recommend: z.object({ enabled: z.boolean().default(true), times: z.array(time()).default(['12:30','20:30']),
      commentEnabled: z.boolean().default(true), maxVideos: z.number().step(1).min(1).max(10).default(3) }).default({}),
    study: z.object({ enabled: z.boolean().default(true), time: time().default('21:00') }).default({}),
    comments: z.object({ enabled: z.boolean().default(true), ownerOnly: z.boolean().default(false) }).default({}).description('条件与去重控制，不另加随机概率'),
    daily: z.object({ enabled: z.boolean().default(true), publishEnabled: z.boolean().default(true), time: time().default('23:50'),
      basePercent: percent(20), stepPercent: percent(20), maxPercent: percent(100) }).default({}),
  }).default({}).description('运营计划：定时触发器在跑，发送与写回由 runner 决定'),
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
});

// DSH Settings projects only volatile fields. A schema alone loads correctly
// but produces no editable card. Keep identity and storage paths ordinary.
const liveFields = ['reply', 'busyWindows', 'voice', 'meme', 'workflows', 'tasks', 'runner', 'proactive'];
for (const key of liveFields) Config.dict[key] = Config.dict[key].volatile();

// 2026-10-30：宿主里插件偶发"整块不挂载"（persistSettings 写了文件，但工具不存在、
// 心跳文件不生成）。没有日志可看，只能自己留痕——apply 一进来就写标记，抛错也写，
// 这样下一次重启就能区分「没加载」「加载了但抛在 provide」「抛在后面」三种情况。
function marker(ctx, config) {
  const dir = String(config.dataDirectory ?? 'D:/Code/Projects/FatFishLife/data/dsh')
  return (name, value) => {
    try {
      mkdirSync(dir, { recursive: true })
      writeFileSync(join(dir, name), JSON.stringify({ at: new Date().toISOString(), ...value }, null, 2) + '\\n')
    } catch { /* 留痕失败不影响挂载 */ }
  };
}

export async function apply(ctx, config) {
  const mark = marker(ctx, config)
  mark('control-mount.json', { stage: 'enter', hasEffect: typeof ctx.effect })
  try {
    await applyInner(ctx, config)
    mark('control-mount.json', { stage: 'done', hasEffect: typeof ctx.effect, tasks: TASKS.length })
  } catch (error) {
    mark('control-error.json', { stage: 'throw', error: error?.stack ?? String(error) })
    throw error
  }
}

async function applyInner(ctx, config) {
  const snapshot = () => Object.fromEntries(Object.entries(config).map(([key, value]) =>
    [key, liveFields.includes(key) ? value.get() : value]));
  const compiled = await persistSettings(snapshot());
  const status = { appliedRevision: compiled.revision, appliedAt: new Date().toISOString(),
    policy: '运行缓存已写入；QQ接入时从此服务读取', media: '概率参数已导出，生产媒体出口未完成',
    workflows: '定时任务已接执行器：B站推荐/收件箱/标签学习/日记，结果见 schedule.results',
    schedule: { executor: '每 30 秒检查一次（进程内定时器，不用系统 cron）', lastDue: null, next: null,
      results: {}, failures: {} },
    proactive: { executor: '每 5 分钟按概率判断一次', lastAt: null, lastResult: null, count: 0 },
    productionCutover: false };
  const settings = { ...compiled, status };
  ctx.provide('fatfishSettings', settings);

  // 定时触发层：判断交给 schedule.mjs（纯函数、有测试），这里负责真执行。
  // 某个任务失败不会影响其它任务；结果写进 schedule-state.json 的 results，
  // 状态卡上能看到「上次跑了什么、成没成」，不用翻日志。
  const scheduleDir = String(config.dataDirectory ?? 'D:/Code/Projects/FatFishLife/data/dsh')
  const proactiveFile = join(scheduleDir, 'proactive-state.json')
  const readJson = (file) => { try { return JSON.parse(readFileSync(file, 'utf8')) } catch { return {} } }
  const writeJson = (file, value) => {
    mkdirSync(dirname(file), { recursive: true })
    writeFileSync(file, JSON.stringify(value, null, 2) + '\n')
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
    return { ctx, config: liveConfig, now, state, saveState: (next) => writeJson(join(scheduleDir, 'task-state.json'), next),
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
      // 2026-10-30 实测：patch 里没写 tasks 时 config.tasks 会落成对象而非数组，
      // 直接 .filter 抛 "(config.tasks ?? TASKS).filter is not a function"，整个 runDue 挂掉
      // （心跳只记 error、任务一条不跑）。这里只认数组，其余回退内置 TASKS。
      const configuredTasks = Array.isArray(config.tasks) ? config.tasks : null
      const tasks = (configuredTasks ?? TASKS).filter((task) => task.enabled !== false)
      const due = dueTasks(now, { lastRun: state.lastRun ?? {}, tasks })
      // 心跳：肉眼确认"定时器真的在跑"和"这一分钟有几个任务到点"。
      // 之前只靠 schedule-state.json 猜，分不清"没到点"和"根本没跑"。
      writeJson(join(scheduleDir, 'scheduler-heartbeat.json'), { at: now.toISOString(), tasks: tasks.length, due: due.length })
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
      const message = error?.message ?? String(error)
      ctx.logger.warn('[fatfish] 定时检查失败：' + message)
      // 失败也要留痕：没有日志目录可看时，这是唯一能确认"跑过但抛了"的证据。
      try { writeJson(join(scheduleDir, 'scheduler-heartbeat.json'), { at: now.toISOString(), error: message }) } catch {}
    } finally {
      running = false
    }
  }
  // 2026-10-30 实测：写在 ctx.effect(...) 里的定时器在这版宿主上从没跑过
  // （工具能调、状态能看，但 lastDue/next 永远是 null，心跳文件也不生成）。
  // 改成和 whale-widget 一样，直接在 apply 里起定时器；挂载即留痕，便于判断
  // "插件加载了" 和 "定时器真的在转" 是两件事。
  writeJson(join(scheduleDir, 'control-mount.json'), { at: new Date().toISOString(),
    hasEffect: typeof ctx.effect, tasks: TASKS.length })
  void runDue()
  const dueTimer = setInterval(() => { void runDue() }, 30_000)
  if (typeof dueTimer.unref === 'function') dueTimer.unref()

  // 主动开口层：每 5 分钟判断一次；真正发不发由 proactive.shouldSpeak 决定
  let proactiveRunning = false
  const tickProactive = async (now = new Date()) => {
    if (proactiveRunning) return
    if (config.runner?.enabled === false) return
    proactiveRunning = true
    try {
      writeJson(join(scheduleDir, 'proactive-heartbeat.json'), { at: now.toISOString() })
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
  const proactiveTimer = setInterval(() => { void tickProactive() }, 5 * 60_000)
  if (typeof proactiveTimer.unref === 'function') proactiveTimer.unref()
  let pending = Promise.resolve();
  ctx.on('loader/volatile-update', () => {
    const current = snapshot();
    const save = async () => {
      const next = await persistSettings(current);
      Object.assign(settings, next);
      status.appliedRevision = next.revision;
      status.appliedAt = new Date().toISOString();
    };
    pending = pending.then(save, save);
    return pending;
  });
  ctx.tools.register(defineTool({ name: 'fatfish_status', description: '查看FatFish配置生效版本、门禁参数与尚未完成的执行器；不调用模型或平台',
    parameters: {}, output: { schema: { type: 'json' }, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }] },
    execute: async () => { await pending; const current = snapshot(); return { ...status,
      busyWindows: current.busyWindows, voice: current.voice, meme: current.meme, workflows: current.workflows,
      tasks: current.tasks, runner: { ...current.runner, ownerChat: ownerChatOf() }, proactive: current.proactive }; } }));
  ctx.logger.info('FatFish配置已应用，版本 ' + compiled.revision.slice(0, 12) + '；定时业务与主动开口已接入');
}
