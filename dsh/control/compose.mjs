// 文案与提示词的**纯函数**层：不联网、不读文件，方便直接跑断言。
// 语气锚点来自 docs/persona/exusiai-voice.md 与 apple-le-examples.md：
// 短、口语、不客套、不播报参数。

/** 秒 → `12:34` / `1:02:03`。 */
export function formatDuration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const rest = total % 60
  const pad = (n) => String(n).padStart(2, '0')
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(rest)}` : `${minutes}:${pad(rest)}`
}

/** 播放量 → `1.2万` / `3.4亿` / `812`。 */
export function formatViews(views) {
  const n = Number(views) || 0
  if (n >= 1e8) return (n / 1e8).toFixed(1).replace(/\.0$/, '') + '亿'
  if (n >= 1e4) return (n / 1e4).toFixed(1).replace(/\.0$/, '') + '万'
  return String(n)
}

/** 单条推荐的展示行；理由由模型给，不合格时干脆不写那句。 */
export function formatRecommendLine(item, reason = '') {
  const title = String(item?.title ?? '').trim()
  const author = String(item?.author?.name ?? item?.author ?? '').trim()
  const bits = []
  if (author) bits.push(author)
  if (item?.duration) bits.push(formatDuration(item.duration))
  if (item?.stat?.view) bits.push(formatViews(item.stat.view) + '播放')
  const meta = bits.length ? `（${bits.join(' · ')}）` : ''
  const text = String(reason ?? '').trim()
  const tail = text ? `\n${text}` : ''
  return `${title}${meta}${tail}\nhttps://www.bilibili.com/video/${item?.bvid ?? ''}`
}

/** 多条推荐的整条消息；空列表返回空串（调用方据此不发）。 */
export function buildRecommendMessage(items, reasons = {}) {
  const lines = (items ?? [])
    .map((item) => formatRecommendLine(item, reasons[item?.bvid] ?? ''))
    .filter((line) => line.trim().length > 0)
  if (!lines.length) return ''
  return lines.join('\n\n')
}

/** 收件箱摘要；没有未读就返回空串。 */
export function buildInboxMessage(items) {
  const rows = (items ?? [])
    .map((item) => {
      const who = String(item?.user?.uname ?? item?.sender ?? '').trim()
      const what = String(item?.title ?? item?.content ?? item?.text ?? '').trim()
      const link = String(item?.url ?? item?.uri ?? '').trim()
      if (!what) return ''
      return `${who ? who + '：' : ''}${what}${link ? '\n' + link : ''}`
    })
    .filter(Boolean)
  if (!rows.length) return ''
  return rows.slice(0, 5).join('\n\n')
}

const PERSONA_RULES = [
  '你在给老大（同一台机器上的开发者）发 B 站分享，用你自己的口气，不是客服。',
  '一到两句，口语，可以带一点自己的吐槽或理由；不要用“推荐理由：”这种标签。',
  '不要复述标题，不要罗列播放量/时长，不要问“你需要吗”，不要说“希望对你有帮助”。',
  '不写 emoji 堆叠，不写 markdown 标题，不写引号包裹的整段话。',
].join('\n')

/** 让模型给一条推荐配一句理由（≤40 字）。 */
export function recommendReasonMessages(item, moodText = '') {
  const title = String(item?.title ?? '')
  const author = String(item?.author?.name ?? '')
  return [
    { role: 'system', content: PERSONA_RULES + (moodText ? `\n当前心情：${moodText}` : '') },
    { role: 'user', content: `视频标题：${title}\nUP主：${author}\n写一句你会说的推荐理由，40 字以内。` },
  ]
}

/** 今天的日记提示词：事实由调用方给，不许模型编。 */
export function diaryMessages({ day, digest, mood, terms, recent }) {
  const facts = [
    `日期：${day}`,
    `今天的心情：${mood?.label ?? '未知'}${mood?.description ? '（' + mood.description + '）' : ''}`,
    `今天记下的事件数：${digest?.events ?? 0}`,
    digest?.kinds && Object.keys(digest.kinds).length
      ? '事件类型分布：' + Object.entries(digest.kinds).map(([k, v]) => `${k} ${v}`).join('、')
      : '',
    Array.isArray(digest?.samples) && digest.samples.length
      ? '片段：' + digest.samples.slice(0, 6).join(' / ')
      : '',
    Array.isArray(terms) && terms.length ? '最近群里的黑话：' + terms.slice(0, 8).join('、') : '',
    Array.isArray(recent) && recent.length
      ? '最近几天的日记：' + recent.slice(0, 2).map((row) => `${row.day}：${String(row.content ?? '').slice(0, 60)}`).join(' | ')
      : '',
  ].filter(Boolean).join('\n')
  return [
    {
      role: 'system',
      content: [
        '你在写自己的日记（第一人称，像随手记在手机备忘录里），不是总结报告。',
        '只写上面给出的事实与感受，不要编造没发生的事、不要写数据统计式句子。',
        '150–300 字，可以分 2–3 段；允许有一点情绪和自嘲，不写标题，不写“今天”开头的模板句。',
      ].join('\n'),
    },
    { role: 'user', content: facts },
  ]
}

/** 主动说一句：给一个场景提示，让模型自己起头。 */
export function proactiveMessages({ mood, hour, terms, lastJournal, quietHint }) {
  const facts = [
    `现在时间：${hour} 点左右`,
    mood?.label ? `你现在的心情：${mood.label}` : '',
    Array.isArray(terms) && terms.length ? '最近群里的说法：' + terms.slice(0, 6).join('、') : '',
    lastJournal ? `你上次日记写到：${String(lastJournal).slice(0, 80)}` : '',
    quietHint ? `场景：${quietHint}` : '',
  ].filter(Boolean).join('\n')
  return [
    {
      role: 'system',
      content: [
        '你突然想跟老大说一句话，就像 QQ 里随手发的一条消息。',
        '一到两句，10–50 字，口语；可以是吐槽、想起的事、问一句、或者单纯冒个泡。',
        '不要开场白（“在吗”“打扰一下”），不要解释你为什么发，不要提 AI 或模型，不要列清单。',
      ].join('\n'),
    },
    { role: 'user', content: facts },
  ]
}
