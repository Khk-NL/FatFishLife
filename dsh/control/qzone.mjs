// QQ 空间（说说）的薄封装。
//
// 走的是本地 onebot-qzone 桥的 HTTP 动作（路径式）：
//   POST http://127.0.0.1:5700/send_msg  {"message":[{"type":"text","data":{"text":"..."}}]}
// 成功返回 {"status":"ok","data":{"tid":"...","source":"official_api"}}。
//
// 这里只管「发」和「探活」，文案在 compose 层，业务判断在 business 层。

import { readFileSync, existsSync } from 'node:fs'

export function qqAccountPaused(file = process.env.FATFISH_QQ_PAUSE_FILE || 'D:/Code/Projects/FatFishLife/data/.qq-account-paused') {
  return existsSync(file)
}

export const DEFAULT_QZONE_BASE = process.env.FATFISH_QZONE_BASE || process.env.QZONE_API_BASE || 'http://127.0.0.1:5700'
const DEFAULT_SECRET_FILE = process.env.FATFISH_QZONE_SECRET_FILE
  || 'D:/Code/Projects/FatFishLife/outputs/secrets/qzone.env'

function accessToken(file) {
  const configured = process.env.QZONE_API_TOKEN || process.env.FATFISH_QZONE_ACCESS_TOKEN
  if (configured) return configured
  try {
    // Same private token source as start_qzone_bridge.ps1; never copy cookies.
    const row = readFileSync(file, 'utf8').match(/^\s*(?:FATFISH_QZONE_ACCESS_TOKEN|QZONE_API_TOKEN)\s*=\s*(.*?)\s*$/m)
    return row?.[1]?.replace(/^(['"])(.*)\1$/, '$2') ?? ''
  } catch (error) {
    if (error?.code === 'ENOENT') return ''
    throw new Error('qzone token source unavailable')
  }
}

async function call(action, body, { base = DEFAULT_QZONE_BASE, timeoutMs = 20_000,
  tokenFile = DEFAULT_SECRET_FILE, token = accessToken(tokenFile) } = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch(`${base.replace(/\/$/, '')}/${action}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json; charset=utf-8',
        ...(token ? { authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(body ?? {}),
      signal: controller.signal,
    })
    if (!response.ok) throw new Error(`qzone ${action} HTTP ${response.status}`)
    const text = await response.text()
    let data
    try {
      data = JSON.parse(text)
    } catch {
      throw new Error(`qzone ${action} 返回的不是 JSON`)
    }
    return data
  } finally {
    clearTimeout(timer)
  }
}

/** 桥是否在线、登录态是否还在；失败不抛，返回 {online:false, reason}。 */
export async function qzoneStatus(options = {}) {
  if (qqAccountPaused(options.pauseFile)) return { online: false, valid: false, reason: 'qq-account-paused' }
  try {
    const data = await call('check_cookie', {}, options)
    const ok = data?.status === 'ok' && Number(data?.retcode ?? 0) === 0
    return {
      online: ok,
      valid: Boolean(data?.data?.valid),
      expired: Boolean(data?.data?.expired),
      qq: data?.data?.qq ?? undefined,
      reason: ok ? undefined : (data?.message ?? data?.wording ?? `retcode ${data?.retcode ?? '?'}`),
    }
  } catch (error) {
    return { online: false, valid: false, reason: error?.message ?? String(error) }
  }
}

/** 发一条说说。成功返回 {ok:true, tid, text}；失败返回 {ok:false, reason}。 */
export async function postThought(text, options = {}) {
  if (qqAccountPaused(options.pauseFile)) return { ok: false, reason: 'qq-account-paused' }
  const body = String(text ?? '').trim()
  if (!body) return { ok: false, reason: 'empty-text' }
  if (body.length > 1000) return { ok: false, reason: 'too-long' }
  if (body.includes('\uFFFD')) return { ok: false, reason: 'invalid-text-encoding' }
  try {
    const data = await call('send_msg', { message: [{ type: 'text', data: { text: body } }] }, options)
    if (data?.status === 'ok' && Number(data?.retcode ?? 0) === 0 && data?.data?.tid) {
      return { ok: true, tid: String(data.data.tid), text: body, source: data.data.source }
    }
    const reason = data?.message ?? data?.wording ?? `retcode ${data?.retcode ?? '?'}`
    return { ok: false, reason: String(reason), text: body }
  } catch (error) {
    // A timed-out publish may already have succeeded upstream. Never retry it.
    return { ok: false, unknown: true, reason: error?.name === 'AbortError'
      ? 'publish-timeout-result-unknown' : String(error?.message ?? error) }
  }
}
