import assert from 'node:assert/strict';
import { test } from 'node:test';
import { installCodexRouting, quotaAllowsCodex, quotaAllowsWorkBuddy } from '../persona/codex-routing.mjs';

const workBuddy = { provider: 'workbuddy', model: 'deepseek-v4.1-flash' };
const codex = { provider: 'openai-codex', model: 'gpt-6.2-sol', reasoningEffort: 'medium' };
const deepSeek = { provider: 'deepseek-official', model: 'deepseek-flash' };

test('quota must be fresh, usable and at or above each minimum', () => {
  const now = 400_000;
  const codexReport = { modelAvailable: true, fetchedAt: 399_000, resetsAt: 401, remaining: 80 };
  const workBuddyReport = { modelAvailable: true, fetchedAt: 399_000, giftCredits: 50 };
  assert.equal(quotaAllowsCodex(codexReport, 80, now), true);
  assert.equal(quotaAllowsCodex({ ...codexReport, remaining: 79 }, 80, now), false);
  assert.equal(quotaAllowsCodex({ ...codexReport, fetchedAt: 200_000 }, 80, now), false);
  assert.equal(quotaAllowsCodex({ ...codexReport, resetsAt: 400 }, 80, now), false);
  assert.equal(quotaAllowsCodex({ ...codexReport, modelAvailable: false }, 80, now), false);
  assert.equal(quotaAllowsWorkBuddy(workBuddyReport, 50, now), true);
  assert.equal(quotaAllowsWorkBuddy({ ...workBuddyReport, giftCredits: 49 }, 50, now), false);
  assert.equal(quotaAllowsWorkBuddy({ ...workBuddyReport, expiresAt: now }, 50, now), false);
  assert.equal(quotaAllowsWorkBuddy({ ...workBuddyReport, giftCredits: 0 }, 0, now), false);
});

async function setup({ balance, remaining, hasWorkBuddy = true, hasCodex = true }) {
  const hooks = {};
  let selected = deepSeek;
  let workBuddyGeneration = 1;
  let codexGeneration = 1;
  let reads = 0;
  const agent = { model: { current: () => selected, select: value => { selected = value; } } };
  const services = {
    fatfishWorkBuddyQuota: !hasWorkBuddy ? undefined : {
      generation: () => workBuddyGeneration,
      read: async () => { reads++; return { modelAvailable: true, fetchedAt: Date.now(), giftCredits: balance }; },
    },
    fatfishCodexQuota: !hasCodex ? undefined : {
      generation: () => codexGeneration,
      read: async () => ({ modelAvailable: true, fetchedAt: Date.now(), resetsAt: Date.now() / 1000 + 60, remaining }),
    },
  };
  installCodexRouting({
    inject(keys, mount) { if (services[keys[0]]) mount({ ...services, effect() {} }); },
    on(name, hook) { hooks[name] = hook; },
  });
  await new Promise(resolve => setImmediate(resolve));
  return { agent, hooks, get selected() { return selected; }, get reads() { return reads; },
    accountChanged() { workBuddyGeneration++; codexGeneration++; } };
}

test('automatic routing prioritizes WorkBuddy, then Codex, and no optional service is a hard dependency', async () => {
  for (const [options, expected] of [
    [{ balance: 50, remaining: 100 }, workBuddy],
    [{ balance: 49, remaining: 80 }, codex],
    [{ balance: 49, remaining: 79 }, deepSeek],
    [{ hasWorkBuddy: false, remaining: 80 }, codex],
    [{ hasCodex: false, balance: 50 }, workBuddy],
    [{ hasWorkBuddy: false, hasCodex: false }, deepSeek],
  ]) {
    const { agent, hooks, ...state } = await setup(options);
    hooks['agent/inbox/claimed']({ agent, turn: 1 });
    assert.deepEqual(agent.model.current(), expected);
    hooks['agent/turn-stopping']({ agent });
    assert.equal(agent.model.current(), deepSeek);
  }
});

test('a turn stays pinned, nontext inputs and manual choices retain their model', async () => {
  const state = await setup({ balance: 51, remaining: 80 });
  const { agent, hooks } = state;
  hooks['agent/inbox/inserted']();
  hooks['agent/inbox/inserted']();
  assert.equal(state.reads, 1);
  hooks['agent/inbox/claimed']({ agent, turn: 1 });
  state.accountChanged();
  hooks['agent/inbox/claimed']({ agent, turn: 1 });
  assert.deepEqual(state.selected, workBuddy);
  hooks['agent/turn-stopping']({ agent });
  hooks['agent/inbox/claimed']({ agent, turn: 2 });
  assert.equal(state.selected, deepSeek);
  hooks['agent/turn-stopping']({ agent });
  hooks['agent/inbox/claimed']({ agent, turn: 3, message: { content: [{ type: 'image' }] } });
  assert.equal(state.selected, deepSeek);
  const manual = { provider: 'some-other-provider', model: 'manual' };
  agent.model.select(manual);
  hooks['agent/turn-stopping']({ agent });
  hooks['agent/inbox/claimed']({ agent, turn: 4 });
  assert.equal(state.selected, manual);
});
