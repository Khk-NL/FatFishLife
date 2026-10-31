import test from 'node:test';
import assert from 'node:assert/strict';
import { walletEffect, transitionDelta } from '../control/wallet.mjs';
import { shouldSpeak } from '../control/proactive.mjs';

const base = { enabled: true, basePercent: 20, dailyCap: 3, minGapMinutes: 30, quietStart: '00:30', quietEnd: '07:30' };
const now = new Date('2026-11-02T15:00:00+08:00'); // 周一下午谷时前，不在忙时窗口

test('钱包档位决定开口意愿', () => {
  assert.equal(walletEffect({ level: 'ok' }).chanceFactor, 1);
  assert.equal(walletEffect({ level: 'low' }).chanceFactor, 0.5);
  assert.equal(walletEffect({ level: 'empty' }).chanceFactor, 0);
  assert.equal(walletEffect(null).level, 'ok');
});

test('见底时主动开口直接闭嘴，理由 hungry', () => {
  const decision = shouldSpeak({ now, config: base, busyWindows: [], state: {}, hunger: walletEffect({ level: 'empty' }), random: () => 0.01 });
  assert.equal(decision.speak, false);
  assert.equal(decision.reason, 'hungry');
});

test('钱紧时候命中率减半', () => {
  const roll = () => 0.15;
  const rich = shouldSpeak({ now, config: base, busyWindows: [], state: {}, hunger: walletEffect({ level: 'ok' }), random: roll });
  const poor = shouldSpeak({ now, config: base, busyWindows: [], state: {}, hunger: walletEffect({ level: 'low' }), random: roll });
  assert.equal(rich.speak, true, '20% 命中，0.15 该中');
  assert.equal(poor.speak, false, '10% 命中，0.15 不该中');
  assert.ok(Math.abs(poor.chance - rich.chance / 2) < 1e-9);
});

test('档位变化才推心情，且第一次读到不算', () => {
  assert.equal(transitionDelta(null, 'low'), null);
  assert.equal(transitionDelta('low', 'low'), null);
  assert.deepEqual(transitionDelta('ok', 'empty'), { delta: -6, reason: '钱包见底了' });
  assert.deepEqual(transitionDelta('low', 'ok'), { delta: 4, reason: '老大充钱了' });
  assert.deepEqual(transitionDelta('empty', 'low'), { delta: 2, reason: '钱包缓过来了' });
});
