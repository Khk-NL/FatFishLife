// bili-cli 的薄封装：读取首页/收件箱，显式授权后发布动态，拿 JSON。
//
// 不在这里做业务判断 —— 选片、文案、发不发都在 business/compose 层，
// 这样可以用假 CLI 结果跑测试，不必联网。

import { execFile } from 'node:child_process'
export { recommendationEvidence } from './video-evidence.mjs'

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
    const child = execFile(bin, args, { timeout, windowsHide: true, maxBuffer: 8 * 1024 * 1024, encoding: 'utf8' },
      (error, stdout) => {
        if (error) {
          // Node's error.message includes argv, which may contain an unpublished post.
          const operation = /^[a-z-]+$/.test(args[0]) ? args[0] : 'command'
          const codes = /"(?:code|retcode)"\s*:\s*"?(-?\d{1,8})"?/.exec(String(stdout ?? ''))
          const detail = codes ? `platform-code=${codes[1]}`
            : typeof error.code === 'number' ? `exit=${error.code}`
              : /^[A-Z_0-9]{1,32}$/.test(error.code ?? '') ? error.code : error.killed ? 'timeout' : 'unconfirmed'
          reject(new Error(`bili ${operation} 失败：${detail}`))
          return
        }
        const text = String(stdout ?? '').trim()
        if (!text) {
          reject(new Error('bili ' + args[0] + ' 没有输出'))
          return
        }
        try {
          resolve(options.receiptIds ? JSON.parse(text, (key, value, source) =>
            ['uid', 'mid', 'msg_key', 'rpid'].includes(key) && typeof value === 'number'
              ? source?.source ?? value : value) : JSON.parse(text))
        } catch {
          reject(new Error('bili ' + args[0] + ' 输出不是 JSON'))
        }
      })
    if (options.stdin !== undefined && child.stdin) {
      // If the command exits before reading, the callback above reports its exit.
      child.stdin.on('error', error => { if (error.code !== 'EPIPE') reject(new Error('bili stdin unavailable')) })
      child.stdin.end(options.stdin, 'utf8')
    }
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

function receiptId(value) {
  if (typeof value === 'number' && !Number.isSafeInteger(value)) return ''
  const id = String(value ?? '')
  return /^[1-9][0-9]*$/.test(id) ? id : ''
}

/** CLI 自行校验主人和私信往来，保留其首次私信限制。 */
export async function recommendDm(text, options = {}) {
  const payload = await (options.run ?? runBili)(['dm', 'send', 'owner', '--file', '-'],
    { ...options, stdin: text, timeoutMs: 90_000, receiptIds: true })
  const uid = receiptId(payload?.data?.uid)
  const messageId = receiptId(payload?.data?.msg_key)
  return payload?.ok === true && payload.data.sent === true && uid && messageId
    ? { status: 'sent', uid, messageId } : { status: 'uncertain' }
}

/** 评论使用本批已确认的私信 UID，并核验平台实际解析的 @。 */
export async function recommendComment(bvid, uid, text, options = {}) {
  const payload = await (options.run ?? runBili)(['comment', 'post', bvid, '--file', '-', '--at', uid, '--wait'],
    { ...options, stdin: text, timeoutMs: 90_000, receiptIds: true })
  const rpid = receiptId(payload?.data?.rpid)
  if (payload?.ok !== true || !rpid) return { status: 'uncertain' }
  const mentions = payload.data.mentions
  const resolved = Array.isArray(mentions) && mentions.some(item => receiptId(item?.mid) === uid && item?.resolved === true)
  return { status: resolved ? 'sent' : 'mention-unconfirmed', rpid }
}

/** 复用现有 bili dynamic post；调用方须传入管理界面的实时发布许可。 */
export async function dynamicPost(text, options = {}) {
  if (options.write !== true) throw new Error('publish-disabled')
  const body = String(text ?? '').trim()
  if (!body) throw new Error('empty-dynamic')
  const payload = await (options.run ?? runBili)(['dynamic', 'post', body], { ...options, timeoutMs: 180_000 })
  if (payload?.ok !== true) throw new Error('bili dynamic post 未确认成功')
  return payload
}
