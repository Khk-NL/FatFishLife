test('runBiliDynamic：默认发一条，写不出来就不发', async () => {
  const posted = [];
  const deps = {
    bili: { dynamicPost: async (text) => { posted.push(text); return { ok: true } } },
    hub: { dayDigest: async () => ({ summary: '群里在聊新卡池' }), moodGet: async () => ({ label: '还不错' }) },
    llm: { chat: async () => '今天新卡池的立绘真好看 (´・ω・`)' },
    config: { workflows: { daily: { publishEnabled: true } } },
  };
  const ok = await runBiliDynamic(deps);
  assert.equal(ok.ok, true);
  assert.equal(posted.length, 1);
  const off = await runBiliDynamic({ ...deps, config: { workflows: { daily: { publishEnabled: false } } } });
  assert.equal(off.skipped, 'publish-disabled');
  const empty = await runBiliDynamic({ ...deps, llm: { chat: async () => '' } });
  assert.equal(empty.ok, false);
  assert.equal(empty.reason, 'empty-dynamic');
});

test('动态发布尊重静默、每日开关与生成期间的关闭，不把业务失败记为成功', async () => {
  let generated = 0; let posted = 0
  const config = { workflows: { daily: { enabled: true, publishEnabled: true } } }
  const deps = { config, currentConfig: () => config,
    hub: { dayDigest: async () => ({}), moodGet: async () => ({}) },
    llm: { chat: async () => { generated++; config.workflows.daily.publishEnabled = false; return '今天好饿' } },
    bili: { dynamicPost: async () => { posted++; return { ok: false } } } }
  assert.equal((await runBiliDynamic(deps)).skipped, 'publish-disabled')
  assert.equal(generated, 1); assert.equal(posted, 0)
  config.workflows.daily.publishEnabled = true
  config.reply = { silent: true }
  assert.equal((await runBiliDynamic(deps)).skipped, 'silent')
  config.reply.silent = false; config.workflows.daily.enabled = false
  assert.equal((await runBiliDynamic(deps)).skipped, 'publish-disabled')
  assert.equal(generated, 1)
  config.workflows.daily.enabled = true
  deps.llm.chat = async () => '今天好饿'
  assert.equal((await runBiliDynamic(deps)).reason, 'dynamic-not-confirmed')
  assert.equal(posted, 1)
})

// 定时业务与主动开口的离线测试：全部用假依赖，不联网、不发 QQ、不花 token。
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import {
  buildInboxMessage, buildRecommendMessage, formatDuration, formatViews, formatRecommendLine,
} from '../control/compose.mjs'
import { runBiliDynamic, runBiliRecommend, runDiary, runQzoneThought, runTask } from '../control/business.mjs'
import { inBusyWindow, inQuietHours, minutesOfDay, runProactive, shouldSpeak } from '../control/proactive.mjs'

test('空间桥离线或登录过期时不花模型费用生成待发正文', async () => {
  for (const status of [{ online: false }, { online: true, valid: false }]) {
    const result = await runQzoneThought({ config: {}, qzoneStatus: async () => status,
      llm: { chat: async () => { throw new Error('must not generate') } },
      postThought: async () => { throw new Error('must not post') } })
    assert.equal(result.ok, false)
    assert.match(result.reason, /qzone-(bridge-offline|login-invalid)/)
  }
})

const video = (bvid, title, extra = {}) => ({
  bvid, title, duration: 754, stat: { view: 123456 }, author: { name: '某UP' }, ...extra,
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

const videoEvidence = async bvid => ({ title: '示例 ' + bvid, description: '画面来源测试',
  manifest: 'cell 1 (r1c1, image 1) = 00:00–00:05', imageUrl: 'data:image/png;base64,AA==' })
const visualReasons = async (messages, options) => {
  assert.equal(options.model, 'deepseek-flash')
  assert.equal(options.thinking, false)
  const blocks = messages[1].content
  assert.equal(blocks.length % 2, 0)
  const recommendations = blocks.filter(block => block.type === 'text').map((block, i) => {
    assert.match(blocks[i * 2 + 1].image_url.url, /^data:image\/png;base64,/)
    return { bvid: JSON.parse(block.text).bvid, cell: 1, observation: '角色在两条路口布防',
      comment: '看见两边都守住，本鱼尾巴都翘起来了',
      reason: '两路同时布防那格挺有意思，本鱼想看看怎么省部署位' }
  })
  return JSON.stringify({ recommendations })
}

test('推荐：拿到分镜才发，发完记住 bvid', async () => {
  const sent = []
  const comments = []
  const state = { seenBvid: [] }
  const deps = {
    now: new Date('2026-10-30T12:30:00+08:00'),
    config: { workflows: { recommend: { commentEnabled: true } } },
    state,
    saveState: async () => {},
    log: silentLog,
    send: async () => assert.fail('Bilibili recommendations must not go through QQ'),
    bili: { recommend: async () => [video('BVaaa', '明日方舟 界园新干员'), video('BVbbb', '完全无关的标题')],
      recommendationEvidence: videoEvidence,
      recommendDm: async text => { sent.push(text); return { status: 'sent', uid: '123', messageId: '456' } },
      recommendComment: async (...args) => { comments.push(args); return { status: 'sent', rpid: '789' } },
    },
    llm: { chat: visualReasons },
    hub: {},
  }
  const outcome = await runBiliRecommend(deps)
  assert.equal(outcome.ok, true)
  assert.equal(outcome.sent, 1)
  assert.equal(sent.length, 1)
  assert.match(sent[0], /BVaaa/)
  assert.doesNotMatch(sent[0], /BVbbb/)
  assert.match(sent[0], /本鱼/)
  assert.deepEqual(comments[0].slice(0, 2), ['BVaaa', '123'])
  assert.match(comments[0][2], /本鱼/)
  assert.deepEqual(state.seenBvid, ['BVaaa'])

  // 第二次：命中的已经推过，退一步推剩下那条（关键词都没命中时的兜底）
  const again = await runBiliRecommend({ ...deps, state })
  assert.equal(again.sent, 1)
  assert.deepEqual(state.seenBvid, ['BVbbb', 'BVaaa'])

  // 第三次：全都推过了，才应该 no-pick
  const third = await runBiliRecommend({ ...deps, state })
  assert.equal(third.sent, 0)
  assert.equal(third.reason, 'no-pick')
})

test('推荐：私信未确认时不评论，同一个视频也不重发', async () => {
  let dmCalls = 0
  let snapshot
  const deps = {
    config: { workflows: { recommend: { commentEnabled: true } } },
    state: {}, saveState: async (state) => { snapshot = structuredClone(state) }, log: silentLog, llm: { chat: visualReasons },
    bili: { recommend: async () => [video('BVccc', '游戏杂谈')],
      recommendationEvidence: videoEvidence,
      recommendDm: async () => {
        dmCalls++
        assert.equal(snapshot.lastRecommendation.dm.status, 'sending')
        throw new Error('timeout')
      },
      recommendComment: async () => assert.fail('comment without a confirmed DM'),
    },
  }
  const outcome = await runBiliRecommend(deps)
  assert.equal(outcome.sent, 0)
  assert.equal(outcome.dm, 'uncertain')
  assert.equal((await runBiliRecommend({ ...deps, state: snapshot })).reason, 'no-pick')
  assert.equal(dmCalls, 1)
})

test('推荐：去重后仅合批分析一次，按管理界面上限选片', async () => {
  const sent = []
  let modelCalls = 0
  const outcome = await runBiliRecommend({
    config: { workflows: { recommend: { maxVideos: 2, commentEnabled: false } } },
    log: silentLog, state: {}, saveState: async () => {},
    llm: { chat: (...args) => { modelCalls++; return visualReasons(...args) } },
    bili: { recommend: async () => [video('BVa', '明日方舟攻略'), video('BVa', '明日方舟攻略'),
      video('BVb', '游戏音乐'), video('BVc', '科技教程')],
      recommendationEvidence: videoEvidence,
      recommendDm: async text => { sent.push(text); return { status: 'sent', uid: '123', messageId: '456' } },
      recommendComment: async () => assert.fail('comments disabled'),
    },
  })
  assert.deepEqual(outcome.picked, ['BVa', 'BVb'])
  assert.equal(sent.length, 1)
  assert.match(sent[0], /两路同时布防/)
  assert.equal(modelCalls, 1)
})

test('推荐：拿不到画面时不生成，视觉请求失败时不重试或发送', async () => {
  let calls = 0
  const deps = { state: {}, saveState: async () => assert.fail('no write claim'), log: silentLog,
    bili: { recommend: async () => [video('BVccc', '游戏杂谈')], recommendationEvidence: async () => null,
      recommendDm: async () => assert.fail('no recommendation') },
    llm: { chat: async () => { calls++; throw new Error('402') } },
  }
  assert.equal((await runBiliRecommend(deps)).skipped, 'recommendation-storyboard-unavailable')
  assert.equal(calls, 0)
  deps.bili.recommendationEvidence = videoEvidence
  assert.equal((await runBiliRecommend(deps)).reason, 'recommendation-analysis-failed')
  assert.equal(calls, 1)
})

test('推荐回执区分结果缺少画面依据与执行期间暂停', async () => {
  let paused = false
  const deps = { state: {}, saveState: async () => assert.fail('no write claim'), log: silentLog,
    canPublish: () => !paused,
    bili: { recommend: async () => [video('BVccc', '游戏杂谈')], recommendationEvidence: videoEvidence,
      recommendDm: async () => assert.fail('no recommendation') },
    llm: { chat: async () => JSON.stringify({ recommendations: [{ bvid: 'BVccc', cell: 20 }] }) },
  }
  assert.equal((await runBiliRecommend(deps)).skipped, 'recommendation-no-grounded-result')
  deps.llm.chat = async () => {
    paused = true
    return JSON.stringify({ recommendations: [] })
  }
  assert.equal((await runBiliRecommend(deps)).skipped, 'recommendation-paused')
  paused = false
  deps.bili.recommendationEvidence = async () => { paused = true; return null }
  deps.llm.chat = async () => assert.fail('no model call after pause')
  assert.equal((await runBiliRecommend(deps)).skipped, 'recommendation-paused')
  paused = false
  deps.bili.recommend = async () => { paused = true; return [] }
  assert.equal((await runBiliRecommend(deps)).skipped, 'recommendation-paused')
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
  assert.match(file, /tags: \[日记, 大肥鲸\]/)
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

test('consolidateGreetingMessages：带上摘要、心情和“现在几点”的要求', async () => {
  const { consolidateGreetingMessages } = await import('../control/compose.mjs')
  const messages = consolidateGreetingMessages({
    summary: '群里在聊方舟新版本',
    mood: { description: '有点困' },
    terms: ['无敌', '整活'],
    hour: 18,
  })
  const user = messages.find((m) => m.role === 'user')?.content ?? ''
  assert.match(user, /群里在聊方舟新版本/)
  assert.match(user, /有点困/)
  assert.match(user, /无敌、整活/)
  assert.match(user, /现在是 18 点/)
  assert.match(user, /问好|心情|吐槽/)
})

test('consolidateGreetingMessages：没有摘要也能生成，不报错', async () => {
  const { consolidateGreetingMessages } = await import('../control/compose.mjs')
  const messages = consolidateGreetingMessages({ summary: '', hour: 12 })
  const user = messages.find((m) => m.role === 'user')?.content ?? ''
  assert.match(user, /现在是 12 点/)
  assert.equal(messages[0].role, 'system')
})

test('发说说：模型写感想并发出去，失败带原因，关掉发布就跳过', async () => {
  const posted = [];
  const deps = {
    settings: { workflows: { daily: {} } },
    now: () => new Date(2026, 10, 5, 21, 30),
    mood: { description: '还不错' },
    hub: { styleTerms: async () => ({ terms: ['摸鱼', '整活'] }) },
    llm: { chat: async (messages) => {
      const text = messages.map((row) => row.content).join(' ');
      assert.match(text, /感想/);
      assert.match(text, /不写任何群名/);
      return '今天摸鱼摸得心安理得 (´・ω・`)';
    } },
    postThought: async (text) => { posted.push(text); return { ok: true, tid: 'tid-1' }; },
  };
  const out = await runQzoneThought(deps);
  assert.equal(out.ok, true);
  assert.equal(out.tid, 'tid-1');
  assert.equal(posted.length, 1);

  const failed = await runQzoneThought({ ...deps, postThought: async () => ({ ok: false, reason: '未登录' }) });
  assert.equal(failed.ok, false);
  assert.equal(failed.reason, '未登录');

  const skipped = await runQzoneThought({ ...deps, settings: { workflows: { daily: { publishEnabled: false } } } });
  assert.equal(skipped.skipped, 'publish-disabled');
});

test('说说执行读取生产config与Date，关闭或静默时零模型零发布', async () => {
  const calls = []
  const deps = {
    config: { workflows: { daily: { publishEnabled: true } } },
    now: new Date(2026, 10, 5, 21, 30),
    llm: { chat: async () => { calls.push('llm'); return '今天有点开心'; } },
    postThought: async () => { calls.push('post'); return { ok: true, tid: 'receipt' }; },
  }
  assert.equal((await runQzoneThought(deps)).tid, 'receipt')
  for (const config of [
    { workflows: { daily: { publishEnabled: false } } },
    { workflows: { daily: { enabled: false } } },
    { reply: { silent: true } },
    { runner: { enabled: false } },
  ]) {
    calls.length = 0
    assert.ok((await runQzoneThought({ ...deps, config })).skipped)
    assert.deepEqual(calls, [])
  }
})

test('说说生成期间关闭发布，最终出口重读开关并停止发送', async () => {
  let current = { workflows: { daily: { publishEnabled: true } } }
  let posted = 0
  const out = await runQzoneThought({
    config: current,
    currentConfig: () => current,
    llm: { chat: async () => { current = { reply: { silent: true } }; return '准备发出的感想'; } },
    postThought: async () => { posted++; return { ok: true, tid: 'unexpected' }; },
  })
  assert.equal(out.skipped, 'silent')
  assert.equal(posted, 0)
})
