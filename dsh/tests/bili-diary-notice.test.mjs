import assert from 'node:assert/strict'
import test from 'node:test'
import { compactDiaryNotice, isLegacyDiaryNotice } from '../bili-diary-notice.mjs'

test('a diary notice keeps one conversational detail and leaves the digest behind', () => {
  const input = [
    '【给他的信·原文】老大，机甲一下水就喊深海模式，评论区当场玩疯了。',
    '',
    '还有一条热门视频，字幕全是广告。',
    '',
    '【摘要】rpid=123456789，今日 1/3，digest 0。',
  ].join('\n')
  assert.equal(isLegacyDiaryNotice(input), true)
  assert.equal(compactDiaryNotice(input, 50), '老大，机甲一下水就喊深海模式，评论区当场玩疯了')
})

test('diary notice respects the current character limit without cutting a clause in half', () => {
  const text = '老大，机甲一下水就喊深海模式，紧接着评论区密密麻麻全在模仿它说话'
  assert.equal(compactDiaryNotice(text, 23), '老大，机甲一下水就喊深海模式')
  assert.equal(compactDiaryNotice('一直写下去却找不到一句可以完整说完的话', 10), '')
})

test('receipt-only drafts are skipped without affecting other notification classes', () => {
  assert.equal(compactDiaryNotice('【摘要】今日 1/3', 50), '')
  assert.equal(compactDiaryNotice('老大，补记 2 条，rpid=123456789', 50), '')
  assert.equal(isLegacyDiaryNotice('有 2 条评论待审核'), false)
})
