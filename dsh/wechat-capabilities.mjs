import { createHash, createHmac, randomUUID } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { defineTool } from '@deepseek-ai/dsh-tools'

const internal = 'mcp__fatfish__wechat_capability_internal'
const digest = text => createHash('sha256').update(text).digest('hex')
const defaultFolder = () => process.env.FATFISH_DSH_DATA || 'D:/Code/Projects/FatFishLife/data/dsh'
const apps = { outlook: 'outlook', '经典outlook': 'outlook-classic', 'auto-mas': 'automas', automas: 'automas', '学习通': 'xuexitong' }
const spec = {
  wechat_memory_save: ['save', '立即保存本轮主人明确要求记住的文字。内容由微信入口确定。'],
  wechat_memory_find: ['find', '查同一微信私聊的私人记忆。关键词留空时返回最近三条。'],
  wechat_lore: ['lore', '查本地公开知识库的证据与出处。'],
  wechat_desktop_status: ['status', '查本机 Outlook、AUTO-MAS 或学习通是否运行。不读取邮件、课程或账号。'],
  wechat_desktop_open: ['open', '按主人本轮的明确请求打开已注册的桌面应用。应用由入口确定。'],
  wechat_job_submit: ['job', '执行主人本轮明确要求的流程。文档、邮箱无需参数。视频只拟定可公开的随想分镜，按回执说明状态。'],
  wechat_jobs: ['jobs', '查这条微信私聊最近五个工作流的实际处理结果。'],
}

export function ownerMemory(text) {
  if (typeof text !== 'string' || text.length > 200 || /[\r\n]/u.test(text)) return null
  const value = text.trim()
  const request = value.match(/^(?:(?:鲸鲸|小鱼)[，,：:\s]*)?(?:请|帮我)?(?:记住|记下|记一下|存到记忆)\s*[：:,，]?\s*(.+)$/u)
  const preference = /^(?:我(?:一直|更|最|很|特别|不太|不)?(?:喜欢|偏好|习惯)|以后(?:叫我|称呼我))[^？?！!。]+[。！!]?$/u.test(value)
  const candidate = (request?.[1] ?? (preference ? value : '')).trim()
  return /^[^？?]{2,160}$/u.test(candidate) ? { text: candidate, explicit: Boolean(request) } : null
}

export function ownerDesktopApp(text) {
  const result = String(text ?? '').trim().match(/^(?:(?:鲸鲸|小鱼)[，,：:\s]*)?(?:帮我|请)?\s*(?:打开|启动)\s*(outlook|经典\s*outlook|auto-mas|automas|学习通)[。！!]?$/iu)
  return result ? apps[result[1].toLowerCase().replace(/\s+/gu, '')] : ''
}

export function ownerWorkflow(text) {
  const input = String(text ?? '').trim().replace(/^(?:鲸鲸|小鱼)[，,：:\s]*/u, '').replace(/^(?:帮我|请|替我)\s*/u, '')
  if (input.length > 600 || !/^(去|在|总结|查|找|整理|发|把|生成)/u.test(input)) return ''
  if (/^(?:总结|整理|查).{0,20}(?:邮箱|邮件)/u.test(input) && /今天/u.test(input)) return 'mail-today'
  if (!/(?:b\s*站|哔哩哔哩)/iu.test(input) || !/视频/u.test(input)) return ''
  if (/^(?:去|在|发)\s*.{0,14}(?:发(?:个|一条|一个|布|送)|投稿)/u.test(input)) return 'bili-video'
  if (/今天/u.test(input) && /dsh|deepseek harness/iu.test(input) && /插件/u.test(input)
      && /总结|整理|文档/u.test(input) && /桌面/u.test(input)) {
    return /qq/iu.test(input) && /发给我|发我/u.test(input) ? 'bili-report-qq' : 'bili-report'
  }
  return ''
}

function secret(folder) {
  try {
    const key = readFileSync(join(folder, 'wechat-capability.key'))
    return key.length === 32 ? key : null
  } catch (error) {
    if (['ENOENT', 'EACCES', 'EPERM'].includes(error.code)) return null
    throw error
  }
}

async function callHost(hostCtx, folder, { conversation, pending, op, value }, signal = AbortSignal.timeout(12_000)) {
  const key = secret(folder)
  const hostTools = hostCtx.get('tools')
  if (!key || !hostTools?.get(internal)) return null
  const scope = conversation ? digest('wechat\0ilink\0private\0' + conversation) : '0'.repeat(64)
  const turn = digest(scope + '\0' + (pending?.fatfishSource || pending?.id || 'daily'))
  const body = JSON.stringify({ scope, turn, op, value, time: Math.floor(Date.now() / 1000) })
  const mac = createHmac('sha256', key).update(body).digest('hex')
  const id = 'wechat-local-' + randomUUID()
  const batch = await hostTools.execute({
    calls: [{ id, name: internal, arguments: JSON.stringify({ body, mac }) }],
    signal, maxParallelToolCalls: 1,
  }).catch(() => null)
  const result = batch?.results?.find(item => item.callId === id)?.result
  return result && !result.isError && !result.value?.isError ? result.value?.structuredContent : null
}

export function stageWechatNote(hostCtx, conversation, pending, folder = defaultFolder()) {
  if (!pending.fatfishPrivate || pending.fatfishMemory?.explicit || !pending.fatfishMemory?.text) return
  return callHost(hostCtx, folder, { conversation, pending, op: 'stage', value: pending.fatfishMemory.text })
}

export function startWechatMemoryClock(hostCtx, logger, folder = defaultFolder()) {
  let cancelled = false
  let timer
  const run = async (startup = false) => {
    try {
      const result = await callHost(hostCtx, folder, { op: 'flush', value: '' })
      if (result?.committed > 0) logger.info?.(JSON.stringify({ event: 'wechat-notes-committed', count: result.committed }))
    } catch {
      logger.warn?.('WeChat memory consolidation could not be verified')
    }
    if (cancelled) return
    const now = Date.now()
    const local = new Date(now + 8 * 3_600_000)
    const today = Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate(), 15, 30)
    const deadline = today > now ? today : today + 86_400_000
    timer = setTimeout(run, startup ? Math.min(12_000, deadline - now) : deadline - now)
    timer.unref?.()
  }
  void run(true)
  return () => { cancelled = true; clearTimeout(timer) }
}

const recentSticker = new Map()
export async function chooseWechatSticker(hostCtx, conversation, pending, answer, folder = defaultFolder(), random = Math.random) {
  if (!pending.fatfishPrivate || pending.fatfishStop) return null
  const input = pending.fatfishDirect ?? ''
  if (/别发(?:图|表情)|不用发(?:图|表情)|不要发(?:图|表情|图片)|只要文字/u.test(input)) return null
  const explicit = /发.{0,5}(?:表情包|表情|贴纸)/u.test(input)
  const emotion = /(哈哈|嘿嘿|晚安|早安|生气|喜欢|开心|可爱|厉害|抱抱|无语|笑死|可恶|啧|哼|鲸)/u.exec(answer + ' ' + input)
  if (!explicit && (!emotion || random() >= 0.55)) return null
  const tag = { 鲸: '鲸鱼', 哼: '傲娇', 啧: '无语' }[emotion?.[0]] ?? emotion?.[0] ?? ''
  const result = await callHost(hostCtx, folder, { conversation, pending, op: 'sticker',
    value: tag + (explicit ? '|explicit' : '') })
  const previous = recentSticker.get(conversation)
  const candidate = result?.paths?.find?.(value => typeof value === 'string' && value !== previous)
  if (!candidate) return null
  if (recentSticker.size >= 128 && !recentSticker.has(conversation)) recentSticker.delete(recentSticker.keys().next().value)
  recentSticker.set(conversation, candidate)
  return candidate
}

export function installWechatCapabilities(agentCtx, hostCtx, {
  conversation, owner, current, folder = defaultFolder(),
}) {
  const tools = agentCtx.get('tools')
  if (!conversation || !secret(folder)) return { available: () => false }
  const eligible = (name, pending) => Boolean(Object.hasOwn(spec, name) && pending && owner()
    && !pending.abandoned && pending.fatfishPrivate && secret(folder) && hostCtx.get('tools')?.get(internal)
    && (spec[name][0] !== 'save' || pending.fatfishMemory?.explicit)
    && (spec[name][0] !== 'open' || pending.fatfishApp)
    && (spec[name][0] !== 'job' || pending.fatfishWorkflow))
  for (const [name, [op, description]] of Object.entries(spec)) {
    const write = ['save', 'open', 'job'].includes(op)
    tools.register(defineTool({
      name, description,
      parameters: op === 'job' ? {
        title: { type: 'string', description: '视频分镜专用。拟一个最多 42 字的标题。' },
        reflection: { type: 'string', description: '视频分镜专用。用鲸鲸的视角写最多 150 字可公开的随想，避免写入私聊、邮件或未经核实的经历。' },
        shots: { type: 'array', items: { type: 'string' }, description: '视频分镜专用。按顺序写三个动作，每个最多 100 字。' },
      } : write || op === 'jobs' ? {} : op === 'status' ? {
        app: { type: 'string', required: true, description: 'outlook、automas、xuexitong 或 all。' },
      } : {
        query: { type: 'string', required: true, description: '一个简短关键词，最多 72 字。' },
      },
      output: { schema: { type: 'json' }, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }] },
      async execute(args, exec) {
        const pending = current()
        if (!eligible(name, pending) || pending.turn == null || exec.agent?.session?.id !== pending.sessionId) {
          return { ok: false, reason: '当前微信回合没有授权此操作' }
        }
        let value = op === 'save' ? pending.fatfishMemory.text
          : op === 'open' ? pending.fatfishApp : op === 'status' ? args.app
          : op === 'job' ? pending.fatfishWorkflow : op === 'jobs' ? '' : args.query
        if (typeof value !== 'string' || value.length > (op === 'save' ? 160 : 72)) {
          return { ok: false, reason: '参数太长' }
        }
        if (op === 'job' && value === 'bili-video') {
          const { title, reflection, shots } = args
          if (typeof title !== 'string' || title.length > 42 || typeof reflection !== 'string' || reflection.length > 150
              || !Array.isArray(shots) || shots.length !== 3 || shots.some(shot => typeof shot !== 'string' || shot.length > 100)) {
            return { ok: false, reason: '视频分镜需要标题、随想和三个镜头动作' }
          }
          value += '|' + JSON.stringify({ title, reflection, actions: shots })
        }
        if (write ? pending.fatfishWritten : (pending.fatfishReads ?? 0) >= 2) {
          return { ok: false, reason: '本条微信消息的工具额度已用完' }
        }
        if (write) pending.fatfishWritten = true
        else pending.fatfishReads = (pending.fatfishReads ?? 0) + 1
        const report = op === 'job' && ['bili-report', 'bili-report-qq'].includes(value)
        return await callHost(hostCtx, folder, { conversation, pending, op, value },
          AbortSignal.any([exec.signal, AbortSignal.timeout(report ? 24_000 : 12_000)]))
          ?? { ok: false, reason: '能力结果未确认，请勿重试或声称成功' }
      },
    }))
  }
  return { available: name => eligible(name, current()) }
}
