// 中枢 CLI 的调用面：情绪、日记、知识图谱、群风格都由 Python 侧那份实现负责，
// 这里只负责起进程、拿 JSON、把失败原因带回来（不吞错）。

import { execFile } from 'node:child_process'

export const DEFAULT_PYTHON = process.env.FATFISH_PYTHON
  || 'D:/Code/Projects/FatFishLife/.tools/dsh-python/Scripts/python.exe'
export const DEFAULT_HUB_CLI = process.env.FATFISH_HUB_CLI
  || 'D:/Code/Projects/FatFishLife/dsh/service/fatfish_hub_cli.py'
export const DEFAULT_MEMORY_DB = process.env.FATFISH_MEMORY_DB
  || 'D:/Code/Apps/AstrBot/data/plugin_data/astrbot_plugin_fatfish_memory/memory.db'

/**
 * 跑一条 CLI 子命令，返回解析后的 JSON。
 * @param {string[]} args 例如 ['mood-get', '--scope', 'global']
 */
export function runHub(args, options = {}) {
  const python = options.python ?? DEFAULT_PYTHON
  const cli = options.cli ?? DEFAULT_HUB_CLI
  const env = {
    ...process.env,
    PYTHONIOENCODING: 'utf-8',
    FATFISH_MEMORY_DB: options.memoryDb ?? DEFAULT_MEMORY_DB,
    FATFISH_HUB_WRITE: options.write ? '1' : (process.env.FATFISH_HUB_WRITE ?? '0'),
  }
  return new Promise((resolve, reject) => {
    execFile(python, [cli, ...args], {
      timeout: options.timeoutMs ?? 25_000, windowsHide: true, maxBuffer: 4 * 1024 * 1024, env,
    }, (error, stdout, stderr) => {
      if (error) {
        const detail = String(stderr ?? '').trim().split(/\r?\n/).pop() || error.message
        reject(new Error('hub ' + args[0] + ' 失败：' + detail))
        return
      }
      const text = String(stdout ?? '').trim()
      try {
        resolve(JSON.parse(text))
      } catch {
        reject(new Error('hub ' + args[0] + ' 输出不是 JSON'))
      }
    })
  })
}

export const moodGet = (options = {}) => runHub(['mood-get', '--scope', options.scope ?? 'global'], options)
export const moodNudge = (delta, reason, options = {}) =>
  runHub(['mood-nudge', '--delta', String(delta), '--reason', reason ?? '', '--scope', options.scope ?? 'global'],
    { ...options, write: true })
export const journalRecent = (options = {}) => runHub(['journal-recent', '--days', String(options.days ?? 7)], options)
export const journalWrite = (day, content, source, options = {}) =>
  runHub(['journal-write', '--day', day, '--content', content, '--source', source ?? 'dsh'], { ...options, write: true })
export const dayDigest = (day, options = {}) => runHub(['day-digest', '--day', day], options)
export const styleTerms = (options = {}) =>
  runHub(['style-terms', '--days', String(options.days ?? 7), '--limit', String(options.limit ?? 12)], options)
export const loreSearch = (query, options = {}) =>
  runHub(['lore-search', '--query', query, '--limit', String(options.limit ?? 5)], options)
export const loreContext = (query, options = {}) =>
  runHub(['lore-context', '--query', query, '--max-chars', String(options.maxChars ?? 1200)], options)
