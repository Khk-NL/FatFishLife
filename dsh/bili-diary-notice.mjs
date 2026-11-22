const letterHeading = /^\s*【给他的信(?:·原文)?】\s*/u
const summaryHeading = /【(?:摘要|运行记录|运营回执)】/u
const receiptFields = /\b(?:rpid|digest|msg_key)\b|\bquota\s+react\b|今日\s*\d+\s*\/\s*\d+|(?:收藏|跳过|未达门槛|补记)\s*[:=：]?\s*\d/u

export function isLegacyDiaryNotice(text) {
  return letterHeading.test(text)
}

export function compactDiaryNotice(text, maxChars) {
  const paragraph = text.replace(letterHeading, '').split(summaryHeading, 1)[0]
    .trim().split(/\r?\n\s*\r?\n/u, 1)[0].trim()
  const line = paragraph.replace(/\s+/gu, ' ')
  if (!line || receiptFields.test(line)) return ''
  const first = line.split(/[。！？!?]/u, 1)[0].trim()
  if (Array.from(first).length <= maxChars) return first
  const limit = Array.from(first).slice(0, maxChars).join('')
  const comma = limit.lastIndexOf('，')
  return comma >= Math.min(16, Math.floor(maxChars / 2)) ? limit.slice(0, comma).trim() : ''
}
