// 主动开口：判断层是纯函数（可断言），执行层只做「生成一句 + 发出去」。
//
// 三条硬约束（来自 dsh/rules.md 与用户口径）：
//   · 忙碌时段一句都不主动说（那是主人也不该被打扰的时间）
//   · 有最小间隔与每日上限，避免刷屏
//   · 只在配置了 ownerChat 的私聊里说，不往群里主动插话

import { moodNudge } from './hub.mjs'
import { cleanReply } from './llm.mjs'
import { proactiveMessages } from './compose.mjs'

const MINUTE = 60_000

/** 'HH:MM' → 当天分钟数。 */
export function minutesOfDay(at) {
  const hit = /^(\d{1,2}):(\d{2})$/.exec(String(at ?? '').trim())
  if (!hit) return null
  const hour = Number(hit[1])
  const minute = Number(hit[2])
  if (hour > 23 || minute > 59) return null
  return hour * 60 + minute
}

/** 判断某个时刻是否落在忙碌窗口内（跨零点也能算对）。 */
export function inBusyWindow(windows, now) {
  if (!Array.isArray(windows) || !windows.length) return false
  const day = now.getDay()
  const current = now.getHours() * 60 + now.getMinutes()
  for (const window of windows) {
    const start = minutesOfDay(window?.start)
    const end = minutesOfDay(window?.end)
    if (start == null || end == null) continue
    const days = Array.isArray(window?.weekdays) && window.weekdays.length ? window.weekdays.map(Number) : null
    if (days && !days.includes(day)) continue
    if (start === end) continue
    if (start < end) {
      if (current >= start && current < end) return true
    } else if (current >= start || current < end) {
      return true // 跨零点
    }
  }
  return false
}

/** 安静时段（夜里不打扰）。 */
export function inQuietHours(config, now) {
  const start = minutesOfDay(config?.quietStart ?? '00:30')
  const end = minutesOfDay(config?.quietEnd ?? '07:30')
  if (start == null || end == null) return false
  const current = now.getHours() * 60 + now.getMinutes()
  return start < end ? current >= start && current < end : current >= start || current < end
}

function sameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

/**
 * 现在该不该主动说一句。
 * @param {{now: Date, config: object, busyWindows: Array, state: object, random?: () => number}} input
 * @returns {{speak: boolean, reason: string, roll?: number, chance?: number, count?: number}}
 */
export function shouldSpeak({ now, config, busyWindows, state, random = Math.random }) {
  const cfg = config ?? {}
  if (cfg.enabled !== true) return { speak: false, reason: 'disabled' }
  if (inBusyWindow(busyWindows, now)) return { speak: false, reason: 'busy' }
  if (inQuietHours(cfg, now)) return { speak: false, reason: 'quiet' }
  const lastAt = state?.lastAt ? new Date(state.lastAt) : null
  const minGap = Math.max(5, Number(cfg.minGapMinutes ?? 180)) * MINUTE
  if (lastAt && !Number.isNaN(lastAt.getTime()) && now - lastAt < minGap) {
    return { speak: false, reason: 'gap' }
  }
  const dayCount = state?.day && sameDay(new Date(state.day), now) ? Number(state.count ?? 0) : 0
  const cap = Math.max(1, Number(cfg.dailyCap ?? 3))
  if (dayCount >= cap) return { speak: false, reason: 'cap', count: dayCount }
  const chance = Math.min(Math.max(Number(cfg.basePercent ?? 6), 0), 100) / 100
  const roll = random()
  return { speak: roll < chance, reason: roll < chance ? 'roll' : 'miss', roll, chance, count: dayCount }
}

/**
 * 执行一次主动开口。
 * @param {{ctx?: object, config: object, busyWindows: Array, state: object, saveState: Function,
 *          hub: object, llm: object, send: Function, log: Function, now: Date, random?: Function}} deps
 */
export async function runProactive(deps) {
  const { config, busyWindows, state, saveState, hub, llm, send, log, now } = deps
  const decision = shouldSpeak({ now, config: config?.proactive, busyWindows, state, random: deps.random })
  if (!decision.speak) return { ok: true, spoke: false, ...decision }
  const owner = String(config?.runner?.ownerChat || '').trim()
  if (!owner) return { ok: false, spoke: false, reason: 'no-target' }
  let mood = null
  let terms = null
  let recent = null
  try { mood = await hub.moodGet() } catch {}
  try { terms = await hub.styleTerms({ days: 7 }) } catch {}
  try { recent = await hub.journalRecent({ days: 3 }) } catch {}
  const last = recent?.items?.[0]?.content ?? ''
  let text = ''
  try {
    text = cleanReply(await llm.chat(proactiveMessages({
      mood, hour: now.getHours(), terms: terms?.terms ?? [], lastJournal: last,
      quietHint: '外面没什么人说话，你自己待着',
    }), { temperature: 1.1, maxTokens: 160 }), Number(config?.proactive?.maxChars ?? 60))
  } catch (error) {
    log('[fatfish] 主动开口生成失败：' + (error?.message ?? error))
    return { ok: false, spoke: false, reason: 'llm-failed' }
  }
  if (!text) return { ok: false, spoke: false, reason: 'empty' }
  const result = await send(owner, text)
  if (!result?.ok) return { ok: false, spoke: false, reason: result?.reason ?? 'send-failed' }
  const dayCount = state?.day && new Date(state.day).toDateString() === now.toDateString() ? Number(state.count ?? 0) + 1 : 1
  const next = { ...state, lastAt: now.toISOString(), day: now.toISOString(), count: dayCount, lastText: text }
  await saveState?.(next)
  try { await moodNudge(0.05, '主动说了句话') } catch {}
  log('[fatfish] 主动开口：' + text.slice(0, 40))
  return { ok: true, spoke: true, text, count: dayCount, reason: decision.reason }
}
