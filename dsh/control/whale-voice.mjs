export const WHALE_VOICE = [
  '你是吞饭之鲸，小名鲸鲸。自称本鱼或人家，真实身份和操作结果据实说明。',
  '日常回复控制在五十字以内，正文主要用中文逗号，句子结束就换行。网址、代码和完整说明按实际需要保留。',
  '尽量用肯定句，直接说感受、想法或当前结果。用具体反应替代套话。',
  '避开我认、这句话我收下了、接住你、我懂，以及同类迎合话。中文聊天里尽量少写我。',
  'B 站公开评论只写自己的感受，可以提到触动本鱼的画面或一句台词，播放量、排名、评分和汇报资料留在后台。',
].join('\n')

const stockPhrase = /(?:本鱼|人家)(?:认(?:了|同)?|懂(?:了|你)?)(?:[，。！？\s]|$)|(?:这句话|你这话).{0,8}收下|接住(?:你|这份)|我(?:懂|理解|明白|认)/u
const reportMetric = /(?:播放量|弹幕数|点赞数|点赞率|评论数|收藏数|统计|排名|推荐理由|评分|\d+(?:\.\d+)?\s*(?:万|亿|播放|赞|分)|[零一二两三四五六七八九十百千万亿]+\s*(?:次播放|播放|个赞|条弹幕))/u

export function whaleComment(value) {
  const text = String(value ?? '').trim()
  if (!text || stockPhrase.test(text) || reportMetric.test(text) || /https?:|@|#|[\x00-\x08]/u.test(text)) return ''
  const clean = text.replace(/(?<![你有让给找喊跟像为对陪问等])我(?![们方国])/gu, '本鱼')
    .replace(/[。.!！?？；;]+/gu, '\n')
    .replace(/[,、:：—]+/gu, '，')
    .replace(/[^\p{L}\p{N}\p{M}，\n ]/gu, '')
    .split(/\n+/u).map(line => line.trim().replace(/^，+|，+$/gu, '')).filter(Boolean).join('\n')
  return Array.from(clean).length <= 50 ? clean : ''
}
