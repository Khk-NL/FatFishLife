import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { FatFishPolicy } from '../policy.mjs';
import { applyModeCommand, formatModeTable, parseModeCommand, persistGroupMode, policyFilePath } from '../runtime-adapter.mjs';

function tempPolicy(extra = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'fatfish-mode-'));
  const file = join(dir, 'policy.json');
  writeFileSync(file, JSON.stringify({
    adapterId: 'napcat-main', botId: '1670515707', ownerId: '3124904460', silent: false, ...extra,
  }, null, 2));
  process.env.FATFISH_POLICY_FILE = file;
  // 固定到非忙时段（03:00），否则在 09:00-12:00 / 14:00-18:00 跑测试会走到忙时分支。
  const fixed = new Date('2026-10-31T03:00:00+08:00');
  return { file, policy: new FatFishPolicy(JSON.parse(readFileSync(file, 'utf8')), { now: () => fixed }) };
}

test('parseModeCommand 认 /mode 的各种写法', () => {
  assert.deepEqual(parseModeCommand('/mode'), { action: 'list' });
  assert.deepEqual(parseModeCommand('/mode list'), { action: 'list' });
  assert.deepEqual(parseModeCommand('/mode 123456789 listen'), { action: 'set', groupId: '123456789', mode: 'listen' });
  assert.deepEqual(parseModeCommand('/mode 123456789 只听不说'), { action: 'set', groupId: '123456789', mode: 'listen' });
  assert.deepEqual(parseModeCommand('/mode 123456789 只@'), { action: 'set', groupId: '123456789', mode: 'mention' });
  assert.deepEqual(parseModeCommand('/mode 123456789 default'), { action: 'reset', groupId: '123456789' });
  assert.equal(parseModeCommand('/mode 12 listen').action, 'invalid');
  assert.equal(parseModeCommand('/mode 123456789 乱写').action, 'invalid');
  assert.equal(parseModeCommand('/new all'), null);
  assert.equal(parseModeCommand('随便聊聊'), null);
});

test('applyModeCommand 改内存并写回 policy.json', () => {
  const { file, policy } = tempPolicy();
  const result = applyModeCommand(policy, '/mode 987654321 quiet');
  assert.equal(result.ok, true);
  assert.match(result.reply, /完全不理/);
  const saved = JSON.parse(readFileSync(file, 'utf8'));
  assert.equal(saved.groupModes['987654321'], 'quiet');
  assert.equal(saved.groupDefaultMode, 'talk');
  // 同一进程里再读一次，说明内存也生效了
  assert.equal(policy.groupMode('987654321'), 'quiet');
  assert.equal(applyModeCommand(policy, '/mode 987654321 禁言').reply.includes('本来就是'), true);
});

test('applyModeCommand default 删除单独设置', () => {
  const { file, policy } = tempPolicy({ groupModes: { '123456789': 'listen' } });
  const result = applyModeCommand(policy, '/mode 123456789 default');
  assert.equal(result.ok, true);
  assert.equal(policy.groupMode('123456789'), 'talk');
  assert.equal(JSON.parse(readFileSync(file, 'utf8')).groupModes['123456789'], undefined);
});

test('persistGroupMode 保留文件里其它字段', () => {
  const { file, policy } = tempPolicy({ groupCooldownMs: 12345, normalKeywords: ['大肥鲸'] });
  policy.setGroupMode('111111111', 'owner');
  persistGroupMode(policy);
  const saved = JSON.parse(readFileSync(file, 'utf8'));
  assert.equal(saved.groupCooldownMs, 12345);
  assert.deepEqual(saved.normalKeywords, ['大肥鲸']);
  assert.equal(saved.groupModes['111111111'], 'owner');
  assert.equal(policyFilePath(), file);
});

test('formatModeTable 列出已设置的群', () => {
  const { policy } = tempPolicy({ groupModes: { '123456789': 'listen', '987654321': 'quiet' } });
  const text = formatModeTable(policy);
  assert.match(text, /123456789：只听不说/);
  assert.match(text, /987654321：完全不理/);
  assert.match(text, /既听又说/);
});

function groupEvent(overrides = {}) {
  return {
    post_type: 'message', message_type: 'group', self_id: '1670515707',
    user_id: '2000000001', group_id: '123456789', message_id: 'm' + Math.random(),
    message: [{ type: 'text', data: { text: '你好' } }], time: 1793400000,
    ...overrides,
  };
}

test('群模式 listen 只观察不回复', () => {
  const { policy } = tempPolicy({ groupModes: { '123456789': 'listen' } });
  const decision = policy.decide(groupEvent(), { allowAllUsers: true, adminUsers: [], allowFrom: [] });
  assert.equal(decision.kind, 'ignore');
  assert.equal(decision.reason, 'group-listen');
  assert.equal(decision.observe, true);
});

test('群模式 quiet 完全不理，连 @ 也不回', () => {
  const { policy } = tempPolicy({ groupModes: { '123456789': 'quiet' } });
  const decision = policy.decide(groupEvent({
    message: [{ type: 'at', data: { qq: '1670515707' } }, { type: 'text', data: { text: ' 在吗' } }],
  }), { allowAllUsers: true, adminUsers: [], allowFrom: [] });
  assert.equal(decision.kind, 'ignore');
  assert.equal(decision.reason, 'group-quiet');
});

test('群模式 mention 只认真 @', () => {
  const { policy } = tempPolicy({ groupModes: { '123456789': 'mention' } });
  const plain = policy.decide(groupEvent(), { allowAllUsers: true, adminUsers: [], allowFrom: [] });
  assert.equal(plain.kind, 'ignore');
  assert.equal(plain.reason, 'group-mention-only');
  const at = policy.decide(groupEvent({
    message_id: 'm2', message: [{ type: 'at', data: { qq: '1670515707' } }, { type: 'text', data: { text: ' 问你个事' } }],
  }), { allowAllUsers: true, adminUsers: [], allowFrom: [] });
  assert.equal(at.kind, 'social');
});

test('群模式 owner 只回老大', () => {
  const { policy } = tempPolicy({ groupModes: { '123456789': 'owner' } });
  const others = policy.decide(groupEvent(), { allowAllUsers: true, adminUsers: [], allowFrom: [] });
  assert.equal(others.reason, 'group-owner-only');
  const boss = policy.decide(groupEvent({
    user_id: '3124904460', message_id: 'm3',
    message: [{ type: 'at', data: { qq: '1670515707' } }, { type: 'text', data: { text: ' 在吗' } }],
  }), { allowAllUsers: true, adminUsers: [], allowFrom: [] });
  assert.equal(boss.kind, 'social');
});

test('没设过的群按默认 talk 走原有逻辑', () => {
  const { policy } = tempPolicy();
  const decision = policy.decide(groupEvent({
    message: [{ type: 'at', data: { qq: '1670515707' } }, { type: 'text', data: { text: ' 在吗' } }],
  }), { allowAllUsers: true, adminUsers: [], allowFrom: [] });
  assert.equal(policy.groupMode('999999999'), 'talk');
  assert.equal(decision.kind, 'social');
});
