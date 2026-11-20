import { test } from 'node:test';
import assert from 'node:assert/strict';
import { whaleComment } from '../control/whale-voice.mjs';
import { compileSettings } from '../control/settings.mjs';

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
