import assert from 'node:assert/strict';
import { test } from 'node:test';
import { installCodexRouting, quotaAllowsCodex } from '../persona/codex-routing.mjs';

test('Codex routing requires a recent usable five-hour quota above the selected threshold', () => {
  const now = 400_000;
  const report = { modelAvailable: true, fetchedAt: 399_000, resetsAt: 401, remaining: 83 };
  assert.equal(quotaAllowsCodex(report, 80, now), true);
  assert.equal(quotaAllowsCodex(report, 83, now), false);
  assert.equal(quotaAllowsCodex({ ...report, fetchedAt: 200_000 }, 80, now), false);
  assert.equal(quotaAllowsCodex({ ...report, resetsAt: 400 }, 80, now), false);
  assert.equal(quotaAllowsCodex({ ...report, modelAvailable: false }, 80, now), false);
});

test('Only the configured desk route is changed and automatic selection restores its fallback', async () => {
  const hooks = {};
  const fallback = { provider: 'deepseek-official', model: 'deepseek-flash' };
  let selected = fallback;
  let generation = 1;
  const agent = { model: { current: () => selected, select: value => { selected = value; } } };
  installCodexRouting({ inject: (_services, register) => register({
    on: (name, hook) => { hooks[name] = hook; },
    fatfishCodexQuota: { generation: () => generation, read: async () => ({ modelAvailable: true,
      fetchedAt: Date.now(), resetsAt: Date.now() / 1000 + 60, remaining: 100 }) },
  }) });
  await new Promise(resolve => setImmediate(resolve));
  hooks['agent/inbox/claimed']({ agent, turn: 1 });
  assert.deepEqual(selected, { provider: 'openai-codex', model: 'gpt-6.2-sol', reasoningEffort: 'medium' });
  hooks['agent/turn-stopping']({ agent });
  assert.equal(selected, fallback);
  generation++;
  hooks['agent/inbox/claimed']({ agent, turn: 2 });
  assert.equal(selected, fallback);
});
