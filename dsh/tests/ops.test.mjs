import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  MAX_RECOMMENDATIONS, MIN_REASON_LENGTH, RECOMMEND_KEYWORDS,
  buildRecommendationDrafts, reasonIsAcceptable, selectRecommendations,
} from '../control/ops.mjs'

const feed = [
  { bvid: 'BV1', title: '明日方舟 新活动解析' },
  { bvid: 'BV2', title: '猫咪日常' },
  { bvid: 'BV3', title: '苹果新品上手' },
  { bvid: 'BV4', title: '能天使 动画剪辑' },
]

test('只保留命中关键词的条目', () => {
  const { picked } = selectRecommendations(feed)
  assert.deepEqual(picked.map((i) => i.bvid), ['BV1', 'BV3', 'BV4'])
})

test('最多 3 条，超出部分给出原因', () => {
  const many = Array.from({ length: 6 }, (_, i) => ({ bvid: `BV${i}`, title: '明日方舟 相关' }))
  const { picked, skipped } = selectRecommendations(many)
  assert.equal(picked.length, MAX_RECOMMENDATIONS)
  assert.ok(skipped.some((s) => s.reason.includes('上限')))
})

test('已经推过的 bvid 不再出现', () => {
  const { picked, skipped } = selectRecommendations(feed, { seen: ['BV1'] })
  assert.deepEqual(picked.map((i) => i.bvid), ['BV3', 'BV4'])
  assert.ok(skipped.some((s) => s.bvid === 'BV1' && s.reason === '已经推过'))
})

test('没有 bvid 的条目不会被选中（去重靠它）', () => {
  const { picked, skipped } = selectRecommendations([{ title: '明日方舟 无编号' }])
  assert.equal(picked.length, 0)
  assert.ok(skipped.some((s) => s.reason.includes('bvid')))
})

test('空输入不抛错', () => {
  assert.deepEqual(selectRecommendations(undefined).picked, [])
  assert.deepEqual(selectRecommendations([]).skipped, [])
})

test('理由太短的一律剔除，不生成占位文案', () => {
  assert.equal(reasonIsAcceptable('好看'), false)
  assert.equal(reasonIsAcceptable('  这条讲了新干员的机制  '), true)
  const drafts = buildRecommendationDrafts(
    [{ bvid: 'BV1', title: 'A' }, { bvid: 'BV3', title: 'B' }],
    { BV1: '太短', BV3: '这条把新活动的机制讲清楚了' },
  )
  assert.deepEqual(drafts.map((d) => d.bvid), ['BV3'])
})

test('关键词表与 rules.md 第 1 条一致', () => {
  assert.deepEqual(RECOMMEND_KEYWORDS, ['明日方舟', '游戏', '音乐', '能天使', '苹果', '科技'])
  assert.equal(MIN_REASON_LENGTH, 8)
})
