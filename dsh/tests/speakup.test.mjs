import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, readFileSync, utimesSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { ensureSpeakUpTarget, newestInstance, sessionBaseId, speakUpConfigPath, workspaceBucket } from '../control/speakup.mjs';

const identity = { adapterId: 'napcat-main', botId: '1670515707' };
const ownerId = '3124904460';

function sandbox() {
  const home = mkdtempSync(join(tmpdir(), 'speakup-'));
  mkdirSync(join(home, '.dsh'), { recursive: true });
  const base = sessionBaseId(`private:${ownerId}`, identity);
  // 只认 qq-work 工作区的会话桶，桶名由工作区路径生成。
  const bucket = join(home, '.dsh', 'sessions', workspaceBucket());
  const older = join(bucket, `${base}-older01`);
  const newer = join(bucket, `${base}-newer02`);
  for (const dir of [older, newer]) {
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, 'session.v4.jsonl.zstd'), 'x');
  }
  utimesSync(join(older, 'session.v4.jsonl.zstd'), new Date(2026, 0, 1), new Date(2026, 0, 1));
  utimesSync(join(newer, 'session.v4.jsonl.zstd'), new Date(2026, 0, 2), new Date(2026, 0, 2));
  const config = speakUpConfigPath(home);
  writeFileSync(config, JSON.stringify({ 总开关: true, 目标会话: [base] }, null, 2) + '\n');
  return { home, base, older: `${base}-older01`, newer: `${base}-newer02`, config };
}

test('会话基础 id 与 runtime-adapter 的 scope 口径一致', () => {
  assert.equal(
    sessionBaseId('private:3124904460', identity),
    'fatfish-qq-c83cbdc5f4dc930841197746250d300f5cd609035ecb151bcc6e644ed1b829be',
  );
});

test('挑出最新的实例目录，不挑历史残留', () => {
  const box = sandbox();
  assert.equal(newestInstance(join(box.home, '.dsh', 'sessions'), box.base), box.newer);
});

test('把目标会话改成最新实例，并保留其它设置', () => {
  const box = sandbox();
  const out = ensureSpeakUpTarget({ home: box.home, identity, ownerId });
  assert.equal(out.ok, true);
  assert.equal(out.changed, true);
  assert.equal(out.target, box.newer);
  const saved = JSON.parse(readFileSync(box.config, 'utf8'));
  assert.deepEqual(saved.目标会话, [box.newer]);
  assert.equal(saved.总开关, true);
});

test('已经对上就不再写盘（幂等）', () => {
  const box = sandbox();
  ensureSpeakUpTarget({ home: box.home, identity, ownerId });
  const before = readFileSync(box.config, 'utf8');
  const out = ensureSpeakUpTarget({ home: box.home, identity, ownerId });
  assert.equal(out.changed, false);
  assert.equal(readFileSync(box.config, 'utf8'), before);
});

test('没有身份或没有实例时不动配置', () => {
  const box = sandbox();
  assert.equal(ensureSpeakUpTarget({ home: box.home, identity: {}, ownerId }).reason, 'no-identity');
  const empty = mkdtempSync(join(tmpdir(), 'speakup-empty-'));
  mkdirSync(join(empty, '.dsh'), { recursive: true });
  writeFileSync(speakUpConfigPath(empty), JSON.stringify({ 目标会话: [] }));
  assert.equal(ensureSpeakUpTarget({ home: empty, identity, ownerId }).reason, 'no-instance');
});
