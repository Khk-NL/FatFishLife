// 运营定时任务的**判断层**（纯函数，不碰网络、不起定时器）。
//
// 为什么单独拆出来：DSH 侧还没有执行器，而「几点该做什么」这件事本身可以离线验证。
// 把时间判断从调度器里抽出来，执行器（control 插件里的 tick）只负责"到点了就叫"，
// 判断逻辑用 `node --test` 覆盖，不用真等到 23:50。
//
// 规则来源：dsh/rules.md。改时间先改这里，再改文档，别只改文档。

import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

/** 每天的运营任务。`at` 是本地时间 HH:MM。 */
export const TASKS = [
  { id: 'bili-recommend-noon', kind: 'bili-recommend', at: '12:30', label: 'B站刷首页+推荐' },
  { id: 'bili-recommend-evening', kind: 'bili-recommend', at: '20:30', label: 'B站刷首页+推荐' },
  { id: 'bili-study', kind: 'bili-study', at: '21:00', label: 'B站标签学习' },
  { id: 'diary', kind: 'diary', at: '23:50', label: '日记与成长总结' },
]

/** 默认宽限：错过超过这个分钟数就不补跑，避免停机一夜后一次性全放出来。 */
export const DEFAULT_GRACE_MINUTES = 60

/** 'HH:MM' → 当天的分钟数。 */
export function minutesOfDay(at) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(at ?? '').trim())
  if (!m) throw new Error(`时间格式应为 HH:MM：${at}`)
  const hour = Number(m[1])
  const minute = Number(m[2])
  if (hour > 23 || minute > 59) throw new Error(`时间越界：${at}`)
  return hour * 60 + minute
}

/** 把 `now` 那天的某个 HH:MM 变成本地 Date。 */
export function scheduledFor(now, at) {
  const base = new Date(now)
  const total = minutesOfDay(at)
  base.setHours(Math.floor(total / 60), total % 60, 0, 0)
  return base
}

/**
 * 当前该跑哪些任务。
 * @param {Date} now 当前时间
 * @param {{tasks?: Array, lastRun?: Record<string, string|Date>, graceMinutes?: number}} [options]
 * @returns {Array<{id: string, kind: string, scheduledFor: string, lateMinutes: number}>}
 */
export function dueTasks(now, options = {}) {
  const tasks = options.tasks ?? TASKS
  const lastRun = options.lastRun ?? {}
  const grace = options.graceMinutes ?? DEFAULT_GRACE_MINUTES
  const due = []
  for (const task of tasks) {
    const target = scheduledFor(now, task.at)
    const lateMinutes = (now - target) / 60000
    if (lateMinutes < 0) continue                    // 还没到点
    if (lateMinutes > grace) continue                // 错过太久，不补
    const previous = lastRun[task.id]
    if (previous) {
      const last = previous instanceof Date ? previous : new Date(previous)
      if (!Number.isNaN(last.getTime()) && last >= target) continue   // 今天已经跑过
    }
    due.push({
      id: task.id,
      kind: task.kind,
      scheduledFor: target.toISOString(),
      lateMinutes: Math.round(lateMinutes),
    })
  }
  return due
}

/** 下一个待跑的任务（用于日志与自检显示）。 */
export function nextRun(now, tasks = TASKS) {
  const upcoming = tasks
    .map((task) => {
      let target = scheduledFor(now, task.at)
      if (target <= now) target = new Date(target.getTime() + 24 * 3600 * 1000)
      return { id: task.id, kind: task.kind, at: task.at, when: target }
    })
    .sort((a, b) => a.when - b.when)
  return upcoming[0] ?? null
}
// ── 状态持久化 ───────────────────────────────────────────────
// 只存"上次跑过的时间"，重启后不重复触发。文件放在插件的 dataDirectory，
// 和设置缓存同处，方便一起备份。

export function statePath(dir) {
  return join(dir, 'schedule-state.json')
}

export function readState(dir) {
  try {
    return JSON.parse(readFileSync(statePath(dir), 'utf8'))
  } catch {
    return {}
  }
}

export function writeState(dir, state) {
  mkdirSync(dir, { recursive: true })
  writeFileSync(statePath(dir), JSON.stringify(state, null, 2) + '\n')
}