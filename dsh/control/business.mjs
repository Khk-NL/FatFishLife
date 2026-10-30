// 定时任务的**执行层**：把「到点了」变成真事（刷 B 站、学标签、写日记）。
//
// 依赖全部注入：bili / llm / hub / send / state。这样测试里可以用假的
// 实现，不需要 QQ 在线、不需要联网、也不花 token。
// 发送目标由 runner.ownerChat / runner.groupChats 决定，空则不发。

import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { selectRecommendations } from './ops.mjs'
import { buildInboxMessage, buildRecommendMessage, diaryMessages, recommendReasonMessages } from './compose.mjs'
import { cleanReply } from './llm.mjs'

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
      reasons[item.bvid] = cleanReply(await llm.chat(recommendReasonMessages(item, mood?.description ?? '')), 40)
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
export async function runTask(task, deps) {
  const kind = task?.kind
  if (kind === 'bili-recommend') return runBiliRecommend(deps)
  if (kind === 'bili-inbox') return runBiliInbox(deps)
  if (kind === 'bili-study') return runBiliStudy(deps)
  if (kind === 'diary') return runDiary(deps)
  return { ok: false, reason: 'unknown-kind:' + String(kind) }
}
