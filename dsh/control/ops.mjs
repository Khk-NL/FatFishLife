// 运营规则的**筛选层**（纯函数）。来源：dsh/rules.md 第 1、2 条。
//
// 为什么单独拆：真正的发送要等 QQ 桥和媒体出口，但"哪些视频值得推、推几条、
// 哪些已经推过"这件事和平台无关，可以离线验证。执行器以后只要 feed 数据进来
// 调这里就行。
//
// 边界（照抄 rules.md，别凭印象改）：
//   · 标题命中关键词才留
//   · 最多 3 条
//   · 发过的 bvid 不再发
//   · 没理由就不发（推荐理由至少 8 个字，和分享闸门一致）

/** rules.md 第 1 条的关键词。 */
export const RECOMMEND_KEYWORDS = ['明日方舟', '游戏', '音乐', '能天使', '苹果', '科技']

/** 每天最多推荐几条。 */
export const MAX_RECOMMENDATIONS = 3

/** 推荐理由的最小长度，与分享闸门的 --reason ≥8 字对齐。 */
export const MIN_REASON_LENGTH = 8

/**
 * 从推荐流里挑出值得推的视频。
 * @param {Array<{bvid?: string, title?: string, seen?: boolean}>} items 首页推荐流
 * @param {{seen?: string[], keywords?: string[], limit?: number}} [options]
 * @returns {{picked: Array, skipped: Array<{bvid: string, reason: string}>}}
 */
export function selectRecommendations(items, options = {}) {
  const seen = new Set((options.seen ?? []).map(String))
  const keywords = options.keywords ?? RECOMMEND_KEYWORDS
  const limit = options.limit ?? MAX_RECOMMENDATIONS
  const picked = []
  const skipped = []

  for (const item of items ?? []) {
    const bvid = String(item?.bvid ?? '').trim()
    const title = String(item?.title ?? '')
    if (!bvid) { skipped.push({ bvid: '', reason: '没有 bvid，无法去重' }); continue }
    if (seen.has(bvid)) { skipped.push({ bvid, reason: '已经推过' }); continue }
    if (picked.length >= limit) { skipped.push({ bvid, reason: `已达每日上限 ${limit} 条` }); continue }
    const hit = keywords.find((word) => title.includes(word))
    if (!hit) { skipped.push({ bvid, reason: '标题未命中关键词' }); continue }
    picked.push({ bvid, title, keyword: hit, seen: item.seen !== false })
  }
  return { picked, skipped }
}

/** 推荐理由是否够格：太短的理由等于没说。 */
export function reasonIsAcceptable(reason) {
  return String(reason ?? '').trim().length >= MIN_REASON_LENGTH
}

/**
 * 把筛选结果和理由合成待发条目；理由不合格的直接剔除，不生成占位文案。
 * @param {Array<{bvid: string, title: string}>} picked
 * @param {Record<string, string>} reasons bvid → 理由
 */
export function buildRecommendationDrafts(picked, reasons = {}) {
  return (picked ?? [])
    .map((item) => ({ ...item, reason: String(reasons[item.bvid] ?? '').trim() }))
    .filter((item) => reasonIsAcceptable(item.reason))
}
