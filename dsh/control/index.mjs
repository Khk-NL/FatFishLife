import z from '@deepseek-ai/schemastery';
import { defineTool } from '@deepseek-ai/dsh-tools';
import { DEFAULT_WINDOWS, persistSettings } from './settings.mjs';
import { dueTasks, nextRun, readState, writeState } from './schedule.mjs';
import { existsSync, readFileSync } from 'node:fs';

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
  }).default({}).description('运营执行器尚未注册：这里保存目标计划，当前不会据此自动发动态、评论或定时消息'),
});

// DSH Settings projects only volatile fields. A schema alone loads correctly
// but produces no editable card. Keep identity and storage paths ordinary.
const liveFields = ['reply', 'busyWindows', 'voice', 'meme', 'workflows'];
for (const key of liveFields) Config.dict[key] = Config.dict[key].volatile();

export async function apply(ctx, config) {
  const snapshot = () => Object.fromEntries(Object.entries(config).map(([key, value]) =>
    [key, liveFields.includes(key) ? value.get() : value]));
  const compiled = await persistSettings(snapshot());
  const status = { appliedRevision: compiled.revision, appliedAt: new Date().toISOString(),
    policy: '运行缓存已写入；QQ接入时从此服务读取', media: '概率参数已导出，生产媒体出口未完成',
    workflows: '目标计划已保存；定时触发器在跑，但业务出口（推荐/学习/日记）尚未接入',
    schedule: { executor: '每 30 秒检查一次（进程内定时器，不用系统 cron）', lastDue: null, next: null },
    productionCutover: false };
  const settings = { ...compiled, status };
  ctx.provide('fatfishSettings', settings);

  // 定时触发层：判断交给 schedule.mjs（12 项测试），这里只负责"到点就叫"。
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
  })
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
      busyWindows: current.busyWindows, voice: current.voice, meme: current.meme, workflows: current.workflows }; } }));
  ctx.logger.info('FatFish配置已应用，版本 ' + compiled.revision.slice(0, 12) + '；运营执行器仍待接入');
}
