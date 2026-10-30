// 心情同步：把 hub（python 侧）记下的调整落进 dsh-feiyu-mood 的状态文件。
//
// 为什么要绕一圈：心情只留一份真源（feiyu-mood 的 state.json），但沙盒里的
// python 进程没有那个目录的写权限（新建/覆盖都是 PermissionError），而宿主
// 进程里的 node 有。所以 python 只写 data/dsh/mood-pending.json 列队，
// 这里每个 tick 把队列合并进真源，再删掉队列文件。

import { readFile, rename, unlink, writeFile } from 'node:fs/promises'
import { homedir } from 'node:os'
import { join } from 'node:path'

export const PENDING_FILE = 'mood-pending.json'

/** 待办队列文件的位置（与 hub.py 的 FATFISH_MOOD_PENDING 保持同一个约定）。 */
export function pendingPath(dataDir) {
  return join(String(dataDir), PENDING_FILE)
}

/** feiyu-mood 的状态文件位置。 */
export function feiyuPath(home = process.env.USERPROFILE || homedir()) {
  return join(home, '.dsh', 'feiyu-mood', 'state.json')
}

/** 取出队列里的条目；格式不认识就当空队列。 */
export function pendingEntries(queue) {
  if (Array.isArray(queue)) return queue
  if (Array.isArray(queue?.entries)) return queue.entries
  return []
}

/**
 * 合并一条调整：改 mood / lastReason / updatedAt，并在 timeline 上留痕。
 * 结构不对（没 moods、条目缺 value）返回 false，调用方负责跳过。
 */
export function mergeIntoState(state, entry) {
  const value = Number(entry?.value)
  if (!Number.isFinite(value) || !state || typeof state !== 'object') return false
  const moods = state.moods
  if (!moods || typeof moods !== 'object') return false
  const preferred = typeof state.lastActive === 'string' && moods[state.lastActive] ? state.lastActive : null
  const key = preferred ?? Object.keys(moods)[0]
  const bucket = moods[key]
  if (!bucket || typeof bucket !== 'object') return false
  const mood = Math.round(Math.max(0, Math.min(100, value)) * 100) / 100
  const at = Number(entry?.at) || Date.now()
  const reason = String(entry?.reason ?? '').slice(0, 120)
  bucket.mood = mood
  if (reason) bucket.lastReason = reason
  bucket.updatedAt = at
  if (Array.isArray(bucket.timeline)) {
    bucket.timeline.push({ at, mood, reason, dims: {} })
    while (bucket.timeline.length > 200) bucket.timeline.shift()
  }
  return true
}

/**
 * 把队列合并进 feiyu-mood；没有队列/没有真源文件时安静返回。
 * 返回 { applied, skipped } 供日志与自检使用。
 */
export async function applyMoodPending({ dataDir, home } = {}) {
  const source = pendingPath(dataDir)
  const target = feiyuPath(home)
  let queue
  try {
    queue = JSON.parse(await readFile(source, 'utf8'))
  } catch {
    return { applied: 0, skipped: 'no-pending' }
  }
  const entries = pendingEntries(queue)
  if (!entries.length) {
    await unlink(source).catch(() => {})
    return { applied: 0, skipped: 'empty' }
  }
  let state
  try {
    state = JSON.parse(await readFile(target, 'utf8'))
  } catch {
    // 插件没装/没写过状态时不要动文件，队列留着下次再试。
    return { applied: 0, skipped: 'no-state' }
  }
  let applied = 0
  for (const entry of entries) {
    if (mergeIntoState(state, entry)) applied += 1
  }
  if (applied) {
    const tmp = `${target}.moodsync-tmp`
    await writeFile(tmp, JSON.stringify(state), 'utf8')
    await rename(tmp, target)
  }
  await unlink(source).catch(() => {})
  return { applied, skipped: applied ? undefined : 'nothing-applied' }
}
