// 定时任务的**执行层**：把「到点了」变成真事（刷 B 站、学标签、写日记）。
//
// 依赖全部注入：bili / llm / hub / send / state。这样测试里可以用假的
// 实现，不需要 QQ 在线、不需要联网、也不花 token。
// 发送目标由 runner.ownerChat / runner.groupChats 决定，空则不发。

import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { execFile } from 'node:child_process'
import { selectRecommendations } from './ops.mjs'
import { buildInboxMessage, buildRecommendMessage, consolidateGreetingMessages, diaryMessages, dynamicMessages, qzoneThoughtMessages, recommendReasonMessages } from './compose.mjs'
import { postThought as qzonePostThought } from './qzone.mjs'
import { cleanReply } from './llm.mjs'
import { DEFAULT_MEMORY_DB, DEFAULT_PYTHON } from './hub.mjs'

const SEEN_LIMIT = 300

/** 本地日期 YYYY-MM-DD（不要用 toISOString，那是 UTC）。 */
export function localDay(now = new Date()) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

function targetsOf(config) {
  const owner = String(config?.runner?.ownerChat || '').trim()
  const groups = (config?.runner?.groupChats ?? []).map((id) => String(id).trim()).filter(Boolean)
  return { owner, groups, all: [owner, ...groups].filter(Boolean) }
}

async function deliver(deps, text) {
  const { config, send, log, state } = deps
  const { all } = targetsOf(config)
  if (!all.length) {
    log('[fatfish] 没有配置发送目标（runner.ownerChat），本次只记录不发')
    return { sent: 0, skipped: 'no-target' }
  }
  const results = []
  for (const chatId of all) {
    const result = await send(chatId, text)
    results.push({ chatId, ok: result?.ok === true, reason: result?.reason })
  }
  const sent = results.filter((row) => row.ok).length
  if (state) {
    state.lastDelivery = { at: new Date().toISOString(), sent, of: all.length }
  }
  return { sent, results }
}

/** B 站推荐：筛片 → 让模型各写一句理由 → 发一条。 */
export async function runBiliRecommend(deps) {
  const { bili, llm, mood, log, state } = deps
  const items = await bili.recommend({ count: 14 })
  const seen = Array.isArray(state?.seenBvid) ? state.seenBvid : []
  const { picked, skipped } = selectRecommendations(items, { seen, limit: 2 })
  log(`[fatfish] B站推荐：候选 ${items.length} 条，选中 ${picked.length} 条，跳过 ${skipped.length} 条`)
  if (!picked.length) return { ok: true, sent: 0, reason: 'no-pick' }
  const reasons = {}
  for (const item of picked) {
    try {
      reasons[item.bvid] = cleanReply(await llm.chat(recommendReasonMessages(item, mood?.description ?? '')), 60)
    } catch (error) {
      log('[fatfish] 推荐理由生成失败：' + (error?.message ?? error))
    }
  }
  const text = buildRecommendMessage(picked, reasons)
  if (!text) return { ok: true, sent: 0, reason: 'empty-text' }
  const outcome = await deliver(deps, text)
  if (outcome.sent > 0 && state) {
    const next = [...picked.map((item) => item.bvid), ...seen].slice(0, SEEN_LIMIT)
    state.seenBvid = next
    await deps.saveState?.(state)
  }
  return { ok: outcome.sent > 0, sent: outcome.sent, picked: picked.map((item) => item.bvid), ...outcome }
}

/** 收件箱摘要：有未读就发，没有就静默。 */
export async function runBiliInbox(deps) {
  const items = await deps.bili.inbox({ limit: 5 })
  const text = buildInboxMessage(items)
  if (!text) return { ok: true, sent: 0, reason: 'empty-inbox' }
  const outcome = await deliver(deps, 'B站有动静：\n' + text)
  return { ok: outcome.sent > 0, sent: outcome.sent, count: items.length, ...outcome }
}

/** 标签学习：从今日 B 站标题里抽 5 个说法，落盘等注入层消费。 */
export async function runBiliStudy(deps) {
  const { bili, llm, log, config, now } = deps
  const items = await bili.recommend({ count: 20 })
  const titles = items.map((item) => String(item?.title ?? '')).filter(Boolean)
  if (!titles.length) return { ok: true, learned: 0, reason: 'no-titles' }
  const messages = [
    { role: 'system', content: '从这些视频标题里挑出 5 个像「梗」或「流行说法」的短词，每行一个，不要编号、不要解释。' },
    { role: 'user', content: titles.join('\n') },
  ]
  let terms = []
  try {
    const raw = await llm.chat(messages, { temperature: 0.4, maxTokens: 120 })
    terms = String(raw ?? '').split(/\r?\n/).map((line) => line.replace(/^[\s\d.\-、]+/, '').trim())
      .filter((term) => term.length >= 2 && term.length <= 12).slice(0, 5)
  } catch (error) {
    log('[fatfish] 标签学习失败：' + (error?.message ?? error))
  }
  const dir = String(config?.dataDirectory ?? 'D:/Code/Projects/FatFishLife/data/dsh')
  const file = join(dir, 'style-learned.jsonl')
  if (terms.length) {
    try {
      mkdirSync(dir, { recursive: true })
      writeFileSync(file, JSON.stringify({ day: localDay(now), at: new Date().toISOString(), terms }) + '\n', { flag: 'a' })
    } catch (error) {
      log('[fatfish] 标签落盘失败：' + (error?.message ?? error))
    }
  }
  return { ok: terms.length > 0, learned: terms.length, terms }
}

/** 日记：事实来自中枢，文字由模型写，写成 Obsidian 笔记 + 记忆库 journal。 */
export async function runDiary(deps) {
  const { hub, llm, log, config, now } = deps
  const day = localDay(now)
  const [digest, mood, terms, recent] = await Promise.all([
    hub.dayDigest(day).catch((error) => { log('[fatfish] day-digest 失败：' + error.message); return null }),
    hub.moodGet().catch(() => null),
    hub.styleTerms({ days: 7 }).catch(() => null),
    hub.journalRecent({ days: 7 }).catch(() => null),
  ])
  const content = cleanReply(await llm.chat(diaryMessages({
    day, digest, mood, terms: terms?.terms ?? [], recent: recent?.items ?? [],
  }), { temperature: 1.0, maxTokens: 700 }), 1600)
  if (!content) return { ok: false, reason: 'empty-diary' }
  let journal = null
  try {
    journal = await hub.journalWrite(day, content, 'dsh-diary')
  } catch (error) {
    log('[fatfish] 日记写入记忆库失败：' + (error?.message ?? error))
  }
  let file = ''
  const dir = String(config?.runner?.diaryDir ?? '')
  if (dir) {
    try {
      mkdirSync(dir, { recursive: true })
      file = join(dir, `${day}.md`)
      const front = ['---', `date: ${day}`, 'tags: [日记, 大肥鲸]', 'source: dsh-fatfish', '---', ''].join('\n')
      writeFileSync(file, front + content + '\n', 'utf8')
    } catch (error) {
      log('[fatfish] 日记写文件失败：' + (error?.message ?? error))
      file = ''
    }
  }
  let sent = 0
  let delivery = null
  if (config?.runner?.diaryToOwner !== false) {
    const head = content.replace(/\s+/g, ' ').slice(0, 120)
    delivery = await deliver(deps, `日记写好了（${day}）：\n${head}…`)
    sent = delivery.sent
  }
  // 发不出去时把原因带出来：没配目标、桥没挂、桥掉线、发送抛错各不相同，
  // 只记 sent:0 下次还得靠猜。
  const reason = sent || !delivery
    ? undefined
    : delivery.skipped ?? delivery.results?.find((row) => !row.ok)?.reason ?? 'not-sent'
  return { ok: true, day, chars: content.length, file, journal, sent,
    ...(reason ? { reason } : {}), delivery }
}

/** 任务总入口：按 kind 分发；未知类型如实报错，不假装成功。 */
/**
 * 峰时攒下的消息，谷时一次总结（记忆 / 成长 / 心情 / 日记）。
 * 真正的逻辑在 scripts/consolidate_peak.py：这里只负责起进程、把结果带回来。
 */
export function runConsolidate(deps) {
  const { log } = deps
  const script = process.env.FATFISH_CONSOLIDATE
    || 'D:/Code/Projects/FatFishLife/scripts/consolidate_peak.py'
  return new Promise((resolve) => {
    execFile(DEFAULT_PYTHON, [script], {
      timeout: 180_000,
      windowsHide: true,
      maxBuffer: 8 * 1024 * 1024,
      env: {
        ...process.env,
        PYTHONIOENCODING: 'utf-8',
        FATFISH_MEMORY_DB: process.env.FATFISH_MEMORY_DB || DEFAULT_MEMORY_DB,
        FATFISH_HUB_WRITE: '1',
      },
    }, (error, stdout, stderr) => {
      const text = String(stdout ?? '').trim().split(/\r?\n/).filter(Boolean).pop() || ''
      let payload = null
      try {
        payload = JSON.parse(text)
      } catch {
        payload = null
      }
      if (error || !payload) {
        const detail = String(stderr ?? '').trim().split(/\r?\n/).pop() || error?.message || 'no-output'
        log('[fatfish] 峰时总结失败：' + detail)
        resolve({ ok: false, reason: detail.slice(0, 200) })
        return
      }
      log(`[fatfish] 峰时总结完成：${payload.items ?? 0} 条 → 记忆 ${payload.written?.memories ?? 0}`
        + ` / 成长 ${payload.written?.growth ?? 0} / 心情 ${payload.written?.mood ?? 0}`)
      // 峰时收工后主动找老大说一句：问好 / 说心情 / 讲学到的事 / 吐槽。
      if (payload.ok !== true || !payload.summary) {
        resolve(payload)
        return
      }
      ;(async () => {
        try {
          let mood = deps.mood
          if (!mood && deps.hub?.moodGet) {
            try { mood = await deps.hub.moodGet() } catch { mood = undefined }
          }
          const messages = consolidateGreetingMessages({
            summary: payload.summary,
            mood,
            terms: Array.isArray(deps.state?.terms) ? deps.state.terms : [],
            hour: new Date().getHours(),
          })
          const text = cleanReply(await deps.llm.chat(messages), 160)
          if (!text) {
            resolve(payload)
            return
          }
          const outcome = await deliver(deps, text)
          log(`[fatfish] 峰时收工问候：${outcome.sent ? '已发送' : '未发送（' + (outcome.skipped ?? outcome.reason ?? '?') + '）'}`)
          resolve({ ...payload, sent: outcome.sent, greeting: text.slice(0, 40) })
        } catch (error) {
          log('[fatfish] 峰时收工问候失败：' + (error?.message ?? error))
          resolve(payload)
        }
      })()
    })
  })
}

/**
 * 每天发一条 B站图文动态。B站没有开放投稿接口，动态是唯一能自动发的形态。
 * 开关是 workflows.daily.publishEnabled；正文由她自己的口气写，失败就不发，不硬凑。
 */
export async function runBiliDynamic(deps) {
  const { bili, hub, llm, config, log = () => {} } = deps
  const blocked = publicationSkipReason(deps)
  if (blocked) return { ok: true, skipped: blocked }
  const day = localDay(typeof deps.now === 'function' ? deps.now() : deps.now ?? new Date())
  const [digest, mood] = await Promise.all([
    hub.dayDigest(day).catch(() => null),
    hub.moodGet().catch(() => null),
  ])
  const text = cleanReply(await llm.chat(dynamicMessages({ day, digest, mood }), { temperature: 1.05, maxTokens: 200 }), 120)
  if (!text) return { ok: false, reason: 'empty-dynamic' }
  const lateBlock = publicationSkipReason(deps)
  if (lateBlock) return { ok: true, skipped: lateBlock }
  try {
    const result = await bili.dynamicPost(text)
    if (result?.ok !== true) return { ok: false, reason: 'dynamic-not-confirmed' }
    log('[fatfish] 动态已发布：' + text.slice(0, 40))
    return { ok: true, sent: 1, detail: text, result }
  } catch (error) {
    return { ok: false, reason: String(error?.message ?? error).slice(0, 160), detail: text }
  }
}

/** 生成前与真正发布前均核对管理界面的实时门禁。 */
function publicationSkipReason(deps) {
    const settings = deps.currentConfig?.() ?? deps.config ?? deps.settings ?? {}
    if (settings.runner?.enabled === false) return 'runner-disabled'
    if (settings.reply?.silent === true) return 'silent'
    const daily = settings.workflows?.daily ?? {}
    if (daily.enabled === false || daily.publishEnabled === false) return 'publish-disabled'
    if (deps.canPublish && !deps.canPublish()) return 'publish-blocked'
    return null
}

export async function runQzoneThought(deps) {
  const skipped = publicationSkipReason(deps)
  if (skipped) return { ok: true, skipped }
  if (deps.qzoneStatus) {
    const status = await deps.qzoneStatus()
    if (!status?.online) return { ok: false, reason: 'qzone-bridge-offline' }
    if (!status.valid) return { ok: false, reason: 'qzone-login-invalid' }
  }
  const now = typeof deps.now === 'function' ? deps.now() : deps.now ?? new Date()
  const day = localDay(now)
  let mood = null
  try { mood = deps.mood ?? (await deps.hub?.moodGet?.()) ?? null } catch { mood = null }
  let terms = []
  try {
    const learned = await deps.hub?.styleTerms?.({ days: 3, limit: 8 })
    terms = Array.isArray(learned?.terms) ? learned.terms : []
  } catch { terms = [] }
  const messages = qzoneThoughtMessages({ day, mood, terms, hint: deps.hint ?? '' })
  const text = cleanReply(await deps.llm.chat(messages), 70)
  if (!text) return { ok: false, reason: 'empty-text' }
  const finalSkip = publicationSkipReason(deps)
  if (finalSkip) return { ok: true, skipped: finalSkip }
  const post = deps.postThought ?? qzonePostThought
  const result = await post(text)
  if (!result?.ok) return { ok: false, reason: result?.reason ?? 'post-failed', detail: text }
  return { ok: true, sent: 1, detail: text, tid: result.tid }
}

export async function runTask(task, deps) {
  const kind = task?.kind
  if (kind === 'bili-recommend') return runBiliRecommend(deps)
  if (kind === 'bili-inbox') return runBiliInbox(deps)
  if (kind === 'bili-study') return runBiliStudy(deps)
  if (kind === 'diary') return runDiary(deps)
  if (kind === 'consolidate') return runConsolidate(deps)
  if (kind === 'bili-dynamic') return runBiliDynamic(deps)
  if (kind === 'qzone-thought') return runQzoneThought(deps)
  return { ok: false, reason: 'unknown-kind:' + String(kind) }
}
