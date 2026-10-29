// 定时/主动层的发送面：只依赖桥提供的 `dshOnebotTransport` 服务。
//
// 为什么不直接在这里连 NapCat：桥已经处理了敏感词审计、Markdown 清理、
// 断线排队、分段发送。这里再写一套只会分叉。桥没挂载/没连上时如实返回
// 失败原因，不做静默兜底 —— 静默的成功最贵。

/** 取桥的发送面；桥还没挂载时返回 undefined，不抛异常。 */
export function transportOf(ctx) {
  try {
    return ctx.get('dshOnebotTransport')
  } catch {
    return undefined
  }
}

/** 连上了没有。桥的 connected 是 getter，读失败按未连接处理。 */
export function transportOnline(ctx) {
  const t = transportOf(ctx)
  try {
    return Boolean(t?.connected?.())
  } catch {
    return false
  }
}

/**
 * 发一条纯文本。
 * @returns {Promise<{ok: boolean, ids?: string[], reason?: string}>}
 */
export async function sendText(ctx, chatId, text, log = () => {}) {
  const body = String(text ?? '').trim()
  if (!body) return { ok: false, reason: 'empty' }
  if (!chatId) return { ok: false, reason: 'no-chat' }
  const t = transportOf(ctx)
  if (!t) {
    log('[fatfish] 没拿到 dshOnebotTransport（桥未挂载或旧版本），本轮不发送')
    return { ok: false, reason: 'transport-missing' }
  }
  if (!transportOnline(ctx)) {
    log('[fatfish] 桥未连接，消息丢弃：' + chatId)
    return { ok: false, reason: 'offline' }
  }
  try {
    const ids = await t.sendText(chatId, body)
    return { ok: true, ids: Array.isArray(ids) ? ids.map(String) : [] }
  } catch (error) {
    log('[fatfish] 发送失败 ' + chatId + '：' + (error?.name ?? 'Error'))
    return { ok: false, reason: error?.name ?? 'send-failed' }
  }
}

/** 一次发给多个目标，按序返回每条结果（一个失败不影响后面的）。 */
export async function sendMany(ctx, chatIds, text, log = () => {}) {
  const results = []
  for (const chatId of chatIds) {
    results.push({ chatId, ...(await sendText(ctx, chatId, text, log)) })
  }
  return results
}
