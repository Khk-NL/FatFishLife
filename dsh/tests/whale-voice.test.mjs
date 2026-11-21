import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, unlinkSync, rmdirSync } from 'node:fs';
import { join } from 'node:path';
import { whaleComment, whaleVoice } from '../control/whale-voice.mjs';
import { compileSettings } from '../control/settings.mjs';
import { readRuntimeOptions } from '../control/runtime-options.mjs';

test('公开评论输出本鱼的感受，句子用换行', () => {
  assert.equal(whaleComment('我好喜欢这个转身！鼓点一响，尾巴也跟着动。'), '本鱼好喜欢这个转身\n鼓点一响，尾巴也跟着动');
  for (const invalid of ['这句话我收下了', '接住你', '播放量有十万', '二十万播放', '鼓点好听'.repeat(13)]) {
    assert.equal(whaleComment(invalid), '');
  }
});

test('关闭峰闲策略时保留原时段并清空下发的策略时段', () => {
  const busyWindows = [{ start: '09:00', end: '12:00', weekdays: [1] }];
  const config = { busyWindows, reply: {}, voice: {}, meme: {}, workflows: {
    daily: {}, recommend: { times: [] }, study: {}, comments: {},
  } };
  assert.deepEqual(compileSettings(config).policy.busyWindows, busyWindows);
  assert.deepEqual(compileSettings({ ...config, peakEnabled: false }).policy.busyWindows, []);
  assert.equal(config.busyWindows.length, 1);
});

test('设置页导出的播放量和语气长度驱动实际消费，0 保持有效', (t) => {
  const dir = mkdtempSync(join(process.cwd(), '.fatfish-options-'));
  const path = join(dir, 'runtime-behavior.json');
  t.after(() => { unlinkSync(path); rmdirSync(dir); });
  const config = { busyWindows: [], reply: {}, voice: {}, meme: {},
    style: { chatMaxChars: 32, commentMaxChars: 8 }, modelRouting: { workBuddyMinCredits: 72, codexMinRemainingPercent: 67 },
    workflows: { biliMinViews: 0, daily: {}, recommend: { times: [] }, study: {}, comments: {} },
  };
  const { behavior } = compileSettings(config);
  assert.equal(behavior.model_routing.codex_min_remaining_percent, 67);
  writeFileSync(path, JSON.stringify(behavior));
  const options = readRuntimeOptions(path);
  assert.deepEqual(options, { chatMaxChars: 32, commentMaxChars: 8, minimumViews: 0, workBuddyMinimum: 72, codexMinimum: 67 });
  assert.match(whaleVoice(options.chatMaxChars), /32 字/);
  assert.equal(whaleComment('看见两边都守住了', options.commentMaxChars), '看见两边都守住了');
  assert.equal(whaleComment('本鱼好喜欢这个转身', options.commentMaxChars), '');
});
