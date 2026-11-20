import assert from 'node:assert/strict';
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { test } from 'node:test';
import { assembleContext, personaPrefix, validateCard } from '../persona/model.mjs';
import { visibleCapabilities } from '../persona/capabilities.mjs';
import { createWechatPrompt } from '../wechat-shared-context.mjs';

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
