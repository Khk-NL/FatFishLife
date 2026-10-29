// 定时业务与主动开口的离线测试：全部用假依赖，不联网、不发 QQ、不花 token。
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import {
  buildInboxMessage, buildRecommendMessage, formatDuration, formatViews, formatRecommendLine,
} from '../control/compose.mjs'
import { runBiliRecommend, runDiary, runTask } from '../control/business.mjs'
import { inBusyWindow, inQuietHours, minutesOfDay, runProactive, shouldSpeak } from '../control/proactive.mjs'

const video = (bvid, title, extra = {}) => ({
  bvid, title, duration: 754, stat: { view: 23456 }, author: { name: '某UP' }, ...extra,
})

const silentLog = () => {}

function fakeSend() {
  const sent = []
  const send = async (chatId, text) => { sent.push({ chatId, text }); return { ok: true, ids: ['m1'] } }
  return { sent, send }
}

test('时长与播放量按人读的方式格式化', () => {
  assert.equal(formatDuration(754), '12:34')
  assert.equal(formatDuration(3723), '1:02:03')
  assert.equal(formatViews(812), '812')
  assert.equal(formatViews(23456), '2.3万')
  assert.equal(formatViews(120000000), '1.2亿')
})

test('推荐行带链接；没有理由就不多出一行', () => {
  const line = formatRecommendLine(video('BV1xx', '明日方舟新活动'), '这个我一定要看')
  assert.match(line, /^明日方舟新活动/)
  assert.match(line, /https:\/\/www\.bilibili\.com\/video\/BV1xx$/)
  assert.ok(line.includes('这个我一定要看'))
  const bare = formatRecommendLine(video('BV1yy', '纯音乐'), '')
  assert.ok(!bare.includes('\n\n'))
})

test('空列表不生成消息', () => {
  assert.equal(buildRecommendMessage([], {}), '')
  assert.equal(buildInboxMessage([]), '')
})

test('收件箱只取前 5 条且跳过没有内容的项', () => {
  const items = Array.from({ length: 7 }, (_, i) => ({ user: { uname: 'u' + i }, title: 't' + i })).concat([{ user: { uname: 'x' } }])
  const text = buildInboxMessage(items)
  assert.equal(text.split('\n\n').length, 5)
  assert.match(text, /u0：t0/)
})

test('推荐：命中关键词才发，发完记住 bvid', async () => {
  const { sent, send } = fakeSend()
  const state = { seenBvid: [] }
  const deps = {
    now: new Date('2026-10-30T12:30:00+08:00'),
    config: { runner: { ownerChat: 'private:1' }, dataDirectory: tmpdir() },
    state,
    saveState: async (next) => { state.seenBvid = next.seenBvid },
    log: silentLog,
    send,
    bili: { recommend: async () => [video('BVaaa', '明日方舟 界园新干员'), video('BVbbb', '完全无关的标题')] },
    llm: { chat: async () => '这个我盯着看了三遍' },
    hub: {},
  }
  const outcome = await runBiliRecommend(deps)
  assert.equal(outcome.ok, true)
  assert.equal(outcome.sent, 1)
  assert.equal(sent.length, 1)
  assert.ok(sent[0].text.includes('BVaaa'))
  assert.ok(!sent[0].text.includes('BVbbb'))
  assert.deepEqual(state.seenBvid, ['BVaaa'])

  // 第二次：已经推过的会被过滤掉，不应再发
  const again = await runBiliRecommend({ ...deps, state })
  assert.equal(again.sent, 0)
  assert.equal(again.reason, 'no-pick')
})

test('推荐：没有配置发送目标时只记录、不外发', async () => {
  const { sent, send } = fakeSend()
  const deps = {
    now: new Date(), config: { runner: {}, dataDirectory: tmpdir() }, state: {}, saveState: async () => {},
    log: silentLog, send, bili: { recommend: async () => [video('BVccc', '游戏杂谈')] },
    llm: { chat: async () => '还行吧' }, hub: {},
  }
  const outcome = await runBiliRecommend(deps)
  assert.equal(outcome.sent, 0)
  assert.equal(sent.length, 0)
})

test('日记：写文件、写记忆库、给主人发摘要', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'fatfish-diary-'))
  const { sent, send } = fakeSend()
  const journalWrites = []
  const deps = {
    now: new Date('2026-10-30T23:50:00+08:00'),
    config: { runner: { ownerChat: 'private:1', diaryDir: dir }, dataDirectory: tmpdir() },
    state: {}, saveState: async () => {}, log: silentLog, send, bili: {},
    llm: { chat: async () => '今天群里又在刷那个梗，我跟着笑了半天。\n然后去翻了两页书，没看懂。' },
    hub: {
      dayDigest: async () => ({ events: 12, kinds: { message: 10 }, samples: ['群友A：界园'] }),
      moodGet: async () => ({ label: '平静', description: '没什么起伏' }),
      styleTerms: async () => ({ terms: ['界园', '问薪无愧'] }),
      journalRecent: async () => ({ items: [] }),
      journalWrite: async (day, content, source) => { journalWrites.push({ day, content, source }); return { ok: true } },
    },
  }
  const outcome = await runDiary(deps)
  assert.equal(outcome.ok, true)
  assert.equal(outcome.day, '2026-10-30')
  const file = readFileSync(join(dir, '2026-10-30.md'), 'utf8')
  assert.match(file, /tags: \[日记, 苹果乐\]/)
  assert.match(file, /今天群里又在刷那个梗/)
  assert.equal(journalWrites.length, 1)
  assert.equal(journalWrites[0].source, 'dsh-diary')
  assert.equal(sent.length, 1)
  assert.match(sent[0].text, /日记写好了（2026-10-30）/)
  rmSync(dir, { recursive: true, force: true })
})

test('未知任务类型如实报错，不假装成功', async () => {
  const outcome = await runTask({ id: 'x', kind: 'nope' }, {})
  assert.equal(outcome.ok, false)
  assert.equal(outcome.reason, 'unknown-kind:nope')
})

test('忙碌窗口支持跨零点', () => {
  const windows = [{ start: '22:00', end: '02:00', weekdays: [0, 1, 2, 3, 4, 5, 6] }]
  const at = (h, m) => new Date(2026, 9, 30, h, m)
  assert.equal(inBusyWindow(windows, at(23, 30)), true)
  assert.equal(inBusyWindow(windows, at(1, 0)), true)
  assert.equal(inBusyWindow(windows, at(12, 0)), false)
  assert.equal(minutesOfDay('07:05'), 425)
  assert.equal(minutesOfDay('bad'), null)
})

test('安静时段与忙碌时段都能拦住主动开口', () => {
  const cfg = { enabled: true, quietStart: '00:30', quietEnd: '07:30' }
  assert.equal(inQuietHours(cfg, new Date(2026, 9, 30, 3, 0)), true)
  assert.equal(inQuietHours(cfg, new Date(2026, 9, 30, 9, 0)), false)
  const decision = shouldSpeak({ now: new Date(2026, 9, 30, 3, 0), config: cfg, busyWindows: [], state: {} })
  assert.equal(decision.reason, 'quiet')
})

test('主动开口的各道闸门按顺序生效', () => {
  const now = new Date(2026, 9, 30, 15, 0)
  const base = { enabled: true, basePercent: 100, minGapMinutes: 150, dailyCap: 2, quietStart: '00:30', quietEnd: '07:30' }
  assert.equal(shouldSpeak({ now, config: { ...base, enabled: false }, busyWindows: [], state: {} }).reason, 'disabled')
  assert.equal(shouldSpeak({ now, config: base, busyWindows: [{ start: '14:00', end: '18:00', weekdays: [5] }], state: {} }).reason, 'busy')
  assert.equal(shouldSpeak({ now, config: base, busyWindows: [], state: { lastAt: new Date(now.getTime() - 60_000).toISOString() } }).reason, 'gap')
  assert.equal(shouldSpeak({ now, config: base, busyWindows: [], state: { lastAt: null, day: now.toISOString(), count: 2 } }).reason, 'cap')
  const hit = shouldSpeak({ now, config: base, busyWindows: [], state: {}, random: () => 0.01 })
  assert.equal(hit.speak, true)
  const miss = shouldSpeak({ now, config: { ...base, basePercent: 10 }, busyWindows: [], state: {}, random: () => 0.99 })
  assert.equal(miss.speak, false)
  assert.equal(miss.reason, 'miss')
})

test('主动开口成功后写状态并记一次情绪', async () => {
  const { sent, send } = fakeSend()
  let saved = null
  const nudges = []
  const deps = {
    now: new Date(2026, 9, 30, 15, 0),
    config: { runner: { ownerChat: 'private:1' }, proactive: { enabled: true, basePercent: 100, maxChars: 60 } },
    busyWindows: [], state: {}, saveState: async (next) => { saved = next }, log: silentLog, send,
    random: () => 0.1,
    llm: { chat: async () => '窗外在下雨，忽然想吃苹果派。' },
    hub: { moodGet: async () => ({ label: '有点饿' }), styleTerms: async () => ({ terms: [] }), journalRecent: async () => ({ items: [] }) },
  }
  const outcome = await runProactive(deps)
  assert.equal(outcome.spoke, true)
  assert.equal(sent.length, 1)
  assert.equal(sent[0].chatId, 'private:1')
  assert.ok(saved?.lastAt)
  assert.equal(saved.count, 1)
  void nudges
})
