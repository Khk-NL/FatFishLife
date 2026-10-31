import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * 钱包快照：由 MCP 的 deepseek_balance 写入，控制层只读。
 * 结构 { cny, level: 'ok'|'low'|'empty', available, at }
 */
export const WALLET_FILE = 'wallet.json'
export const WALLET_STATE_FILE = 'wallet-state.json'

export function walletPath(dataDir) {
  return join(String(dataDir || '.'), WALLET_FILE)
}

export function walletStatePath(dataDir) {
  return join(String(dataDir || '.'), WALLET_STATE_FILE)
}

export function readWallet(dataDir) {
  try {
    const raw = readFileSync(walletPath(dataDir), 'utf8')
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return null
    return parsed
  } catch {
    return null
  }
}

/**
 * 饿了会怎样：吃得饱正常开口，瘪了就懒，见底就不动。
 * @param {object|null} wallet
 * @returns {{level: string, chanceFactor: number, moodDelta: number, reason: string}}
 */
export function walletEffect(wallet) {
  const level = String(wallet?.level || 'ok')
  if (level === 'empty') return { level, chanceFactor: 0, moodDelta: -8, reason: 'hungry' }
  if (level === 'low') return { level, chanceFactor: 0.5, moodDelta: -3, reason: 'thrifty' }
  return { level: 'ok', chanceFactor: 1, moodDelta: 0, reason: 'ok' }
}

/**
 * 只在档位变化时给一次心情差，避免每次轮询都往下压。
 * @param {string|null} previousLevel
 * @param {string} nextLevel
 * @returns {{delta: number, reason: string} | null}
 */
export function transitionDelta(previousLevel, nextLevel) {
  const before = String(previousLevel || '')
  const after = String(nextLevel || 'ok')
  if (before === after) return null
  if (before === '') return null // 第一次读到余额不算变化
  const rank = { empty: 0, low: 1, ok: 2 }
  const from = rank[before]
  const to = rank[after]
  if (from === undefined || to === undefined) return null
  if (to > from) {
    return { delta: to === 2 ? 4 : 2, reason: to === 2 ? '老大充钱了' : '钱包缓过来了' }
  }
  return { delta: to === 0 ? -6 : -4, reason: to === 0 ? '钱包见底了' : '钱包有点瘪' }
}
