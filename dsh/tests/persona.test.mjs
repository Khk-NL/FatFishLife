import assert from 'node:assert/strict';
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { test } from 'node:test';
import { assembleContext, personaPrefix, validateCard } from '../persona/model.mjs';
import { visibleCapabilities } from '../persona/capabilities.mjs';
import { createWechatPrompt, queryDiaryStatus } from '../wechat-shared-context.mjs';

const card = JSON.parse(readFileSync(new URL('../persona/whale.json', import.meta.url), 'utf8'));

test('channel preview retains the character and omits the group rule in private channels', () => {
  assert.match(personaPrefix(card, 'desktop'), /吞饭之鲸/);
  assert.match(personaPrefix(card, 'qq'), /引用第三方/);
  assert.doesNotMatch(personaPrefix(card, 'wechat'), /引用第三方/);
  assert.doesNotMatch(personaPrefix(card, 'bilibili'), /引用第三方/);
  assert.throws(() => validateCard({ ...card, secret: 'not a card field' }), /未知字段/);
});

test('advisory capability cards show actual names and omit housekeeping', () => {
  assert.deepEqual(visibleCapabilities([
    { name: 'compress' }, { name: 'mcp__fatfish__lore_search' }, { name: 'mcp__fatfish__journal_recent' },
  ], {}, { publicOnly: true }), [
    { id: 'knowledge', label: '查公开资料', tools: ['mcp__fatfish__lore_search'] },
  ]);
  assert.deepEqual(visibleCapabilities([]), []);
});

test('ordinary chatter does no context lookup and configured topic switches take effect', () => {
  let calls = 0;
  const activity = () => { calls++; return '活动结果'; };
  assert.equal(assembleContext(card.context, '好饿，先吃饭', { activity }), '');
  assert.equal(assembleContext(card.context, '今天看了什么', { activity }), '活动结果');
  assert.equal(assembleContext({ ...card.context, activity: false }, '今天看了什么', { activity }), '');
  assert.equal(calls, 1);
});

test('WeChat binds activity and mood snippets to authenticated owner requests only', () => {
  const root = mkdtempSync(join(tmpdir(), 'fish-persona-'));
  try {
    const date = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date());
    writeFileSync(join(root, 'whale-diary.md'), `## 看过\n| 1 | BV1virSBTEst | 方舟活动 | ${date} |备注|\n`);
    writeFileSync(join(root, 'growth.txt'), '这是私人练习摘要');
    const options = { root, growthFile: join(root, 'growth.txt'), currentText: () => '今天看了什么视频' };
    assert.match(createWechatPrompt({ ...options, owner: true })(), /方舟活动/);
    assert.doesNotMatch(createWechatPrompt({ ...options, owner: false })(), /方舟活动/);
    assert.doesNotMatch(createWechatPrompt({ ...options, owner: true, currentText: () => '嗨' })(), /方舟活动|私人练习/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});


test('diary lookup uses the requested Shanghai date, including newly appended top-level dated entries', (t) => {
  const root = mkdtempSync(join(tmpdir(), 'fish-diary-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const diary = join(root, 'whale-diary.md');
  const schedule = join(root, 'schedule-state.json');
  writeFileSync(diary, '## 日记\n### 2026-11-11\n旧记录\n## 给他的信\n旧信\n## 2026-11-20｜回家\n昨晚的新记录\n## 2026-11-21\n今早');
  writeFileSync(schedule, JSON.stringify({ results: { diary: { at: '2026-11-20T15:50:11Z', ok: true } } }));
  const now = new Date('2026-11-21T12:30:00Z');
  assert.equal(queryDiaryStatus('昨天写日记了嘛', { root, schedule, now }),
    '写啦，本鱼留着 2026-11-20 的日记\n日记任务 23:50 完成');
  assert.match(queryDiaryStatus('2026-11-19日记写了没', { root, schedule, now }), /暂时读不到 2026-11-19/);
  assert.equal(queryDiaryStatus('给我写一篇新日记', { root, schedule, now }), undefined);
});
