// 定时/主动层用的大模型调用（直接走 DeepSeek HTTP，不经会话）。
//
// 为什么不复用桥的会话：定时任务是「自己冒一句话」，塞进用户会话会产生
// 假用户消息、污染记忆、还要占一份上下文。这里只求一段短文本。
// 密钥来源：环境变量优先，其次 ~/.dsh/.credentials.yaml 的 refs 段。

import { readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

export const DEFAULT_CREDENTIALS = process.env.FATFISH_CREDENTIALS
  || join(homedir(), '.dsh', '.credentials.yaml')
export const DEFAULT_API_BASE = 'https://api.deepseek.com'

/** 从 credentials.yaml 文本里取 refs 段（只认缩进两格的 NAME: value）。 */
export function parseCredentialRefs(text) {
  const refs = {}
  let inRefs = false
  for (const raw of String(text ?? '').split(/\r?\n/)) {
    if (raw.length > 0 && !raw.startsWith(' ') && !raw.startsWith('#')) {
      inRefs = /^refs:\s*$/.test(raw)
      continue
    }
    if (!inRefs) continue
    const hit = /^\s+([A-Za-z0-9_]+):\s*(.+?)\s*$/.exec(raw)
    if (hit) refs[hit[1]] = hit[2].replace(/^['"]|['"]$/g, '')
  }
  return refs
}

/** 解析出可用的 DeepSeek 密钥；找不到就返回空串（调用方负责报错，不要猜）。 */
export function resolveDeepSeekKey(env = process.env, file = DEFAULT_CREDENTIALS) {
  if (env.DEEPSEEK_API_KEY) return String(env.DEEPSEEK_API_KEY)
  try {
    return parseCredentialRefs(readFileSync(file, 'utf8')).DEEPSEEK_API_KEY ?? ''
  } catch {
    return ''
  }
}

/** 去掉模型爱加的开场与引号，只留一句正文。 */
export function cleanReply(text, maxChars = 120) {
  let body = String(text ?? '').trim()
  body = body.replace(/^```[a-z]*\n?/i, '').replace(/```$/, '').trim()
  body = body.replace(/^(苹果乐|助手|我)[:：]\s*/, '')
  body = body.replace(/^["'“”「」]+|["'“”「」]+$/g, '').trim()
  if (maxChars > 0 && body.length > maxChars) body = body.slice(0, maxChars).trim()
  return body
}

/**
 * 发一次对话补全，返回纯文本。
 * @param {Array<{role: string, content: string}>} messages
 * @param {{key?: string, apiBase?: string, model?: string, temperature?: number,
 *          maxTokens?: number, timeoutMs?: number, fetchImpl?: Function}} [options]
 */
export async function chat(messages, options = {}) {
  const key = options.key ?? resolveDeepSeekKey()
  if (!key) throw new Error('没有可用的 DeepSeek 密钥（环境变量或 ~/.dsh/.credentials.yaml 的 refs）')
  const fetchImpl = options.fetchImpl ?? globalThis.fetch
  if (typeof fetchImpl !== 'function') throw new Error('当前运行时没有 fetch')
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? 45_000)
  try {
    const response = await fetchImpl(`${options.apiBase ?? DEFAULT_API_BASE}/chat/completions`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: `Bearer ${key}` },
      body: JSON.stringify({
        model: options.model ?? 'deepseek-chat',
        messages,
        temperature: options.temperature ?? 0.9,
        max_tokens: options.maxTokens ?? 400,
        stream: false,
      }),
      signal: controller.signal,
    })
    if (!response.ok) throw new Error('DeepSeek HTTP ' + response.status)
    const payload = await response.json()
    const text = payload?.choices?.[0]?.message?.content
    if (typeof text !== 'string' || !text.trim()) throw new Error('DeepSeek 返回空内容')
    return text
  } finally {
    clearTimeout(timer)
  }
}
