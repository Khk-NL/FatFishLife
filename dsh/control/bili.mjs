// bili-cli 的薄封装：只跑读操作（首页推荐、收件箱），拿 JSON。
//
// 不在这里做业务判断 —— 选片、文案、发不发都在 business/compose 层，
// 这样可以用假 CLI 结果跑测试，不必联网。

import { execFile } from 'node:child_process'

export const DEFAULT_BILI_BIN = process.env.FATFISH_BILI_BIN
  || 'D:/Code/Apps/bili-venv/Scripts/bili.exe'

/**
 * 跑一条 bili 子命令并解析 JSON。
 * @returns {Promise<object>} bili 输出的 `data` 部分之外的完整 JSON
 */
export function runBili(args, options = {}) {
  const bin = options.bin ?? DEFAULT_BILI_BIN
  const timeout = options.timeoutMs ?? 30_000
  return new Promise((resolve, reject) => {
    execFile(bin, args, { timeout, windowsHide: true, maxBuffer: 8 * 1024 * 1024, encoding: 'utf8' },
      (error, stdout, stderr) => {
        if (error) {
          const detail = String(stderr ?? '').trim().split(/\r?\n/).pop() || error.message
          reject(new Error('bili ' + args[0] + ' 失败：' + detail))
          return
        }
        const text = String(stdout ?? '').trim()
        if (!text) {
          reject(new Error('bili ' + args[0] + ' 没有输出'))
          return
        }
        try {
          resolve(JSON.parse(text))
        } catch {
          reject(new Error('bili ' + args[0] + ' 输出不是 JSON'))
        }
      })
  })
}

/** 首页推荐（个性化）。返回 items 数组，失败抛错。 */
export async function feedRecommend(options = {}) {
  const count = Math.min(Math.max(Number(options.count ?? 10), 1), 30)
  const args = ['feed', 'recommend', '-n', String(count)]
  if (options.unseen !== false) args.push('--unseen')
  if (options.page) args.push('--page', String(options.page))
  const payload = await runBili(args, options)
  if (payload?.ok === false) throw new Error('bili feed recommend 返回 ok=false')
  return Array.isArray(payload?.data?.items) ? payload.data.items : []
}

/** 未读收件箱：@、回复、系统通知。 */
export async function feedInbox(options = {}) {
  const limit = Math.min(Math.max(Number(options.limit ?? 5), 1), 20)
  const payload = await runBili(['feed', 'inbox', '--limit', String(limit)], options)
  if (payload?.ok === false) throw new Error('bili feed inbox 返回 ok=false')
  const items = payload?.data?.items ?? payload?.data?.messages ?? []
  return Array.isArray(items) ? items : []
}
