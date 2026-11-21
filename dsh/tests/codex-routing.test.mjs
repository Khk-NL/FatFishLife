import assert from 'node:assert/strict';
import { test } from 'node:test';
import { formatWechatQuota, parseWechatServiceQuery } from '../wechat-service-status.mjs';
import { installCodexRouting, quotaAllowsCodex, quotaAllowsWorkBuddy } from '../persona/codex-routing.mjs';

const workBuddy = { provider: 'workbuddy', model: 'deepseek-v4.1-flash' };
const codex = { provider: 'openai-codex', model: 'gpt-6.2-sol', reasoningEffort: 'medium' };
const deepSeek = { provider: 'deepseek-official', model: 'deepseek-flash' };

test('quota must be fresh, usable and at or above each minimum', () => {
  const now = 400_000;
  const codexReport = { modelAvailable: true, fetchedAt: 399_000, resetsAt: 401, remaining: 80,
    weeklyRemaining: 50, weeklyResetsAt: 604800 };
  const limits = { codexMinimum: 80, codexWeeklyMinimum: 50 };
  const workBuddyReport = { modelAvailable: true, fetchedAt: 399_000, giftCredits: 50 };
  assert.equal(quotaAllowsCodex(codexReport, limits, now), true);
  assert.equal(quotaAllowsCodex({ ...codexReport, remaining: 79 }, limits, now), false);
  assert.equal(quotaAllowsCodex({ ...codexReport, weeklyRemaining: 49 }, limits, now), false);
  assert.equal(quotaAllowsCodex({ ...codexReport, weeklyRemaining: undefined }, limits, now), false);
  assert.equal(quotaAllowsCodex({ ...codexReport, weeklyResetsAt: 400 }, limits, now), false);
  assert.equal(quotaAllowsCodex({ ...codexReport, fetchedAt: 200_000 }, limits, now), false);
  assert.equal(quotaAllowsCodex({ ...codexReport, resetsAt: 400 }, limits, now), false);
  assert.equal(quotaAllowsCodex({ ...codexReport, modelAvailable: false }, limits, now), false);
  assert.equal(quotaAllowsWorkBuddy(workBuddyReport, 50, now), true);
  assert.equal(quotaAllowsWorkBuddy({ ...workBuddyReport, giftCredits: 49 }, 50, now), false);
  assert.equal(quotaAllowsWorkBuddy({ ...workBuddyReport, expiresAt: now }, 50, now), false);
  assert.equal(quotaAllowsWorkBuddy({ ...workBuddyReport, giftCredits: 0 }, 0, now), false);
});

async function setup({ balance, remaining, weeklyRemaining = 50, manualCodex = false, hasWorkBuddy = true, hasCodex = true }) {
  const hooks = {};
  const dispose = {};
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
      read: async () => ({ modelAvailable: true, fetchedAt: Date.now(), resetsAt: Date.now() / 1000 + 60, remaining,
        weeklyRemaining, weeklyResetsAt: Date.now() / 1000 + 600 }),
    },
  };
  installCodexRouting({
    inject([key], mount) {
      if (services[key]) mount({ ...services, effect: use => { dispose[key] = use(); } });
    },
    on(name, hook) { hooks[name] = hook; },
  }, { prefersCodex: () => manualCodex, onCodexUnavailable: () => { manualCodex = false; } });
  await new Promise(resolve => setImmediate(resolve));
  return { agent, hooks, get selected() { return selected; }, get reads() { return reads; },
    accountChanged() { workBuddyGeneration++; codexGeneration++; },
    disable(key) { dispose[key]?.(); delete services[key]; } };
}

test('default routing stays on DeepSeek and only explicit Codex selection uses the two quota limits', async () => {
  for (const [options, expected] of [
    [{ balance: 50, remaining: 100 }, workBuddy],
    [{ balance: 49, remaining: 80 }, deepSeek],
    [{ balance: 50, remaining: 80, manualCodex: true }, codex],
    [{ balance: 49, remaining: 79, manualCodex: true }, deepSeek],
    [{ balance: 49, remaining: 80, weeklyRemaining: 49, manualCodex: true }, deepSeek],
    [{ hasWorkBuddy: false, remaining: 80, manualCodex: true }, codex],
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

test('disabling Codex advances to DeepSeek even after an interrupted automatically selected turn', async () => {
  const state = await setup({ balance: 49, remaining: 80, manualCodex: true });
  state.hooks['agent/inbox/claimed']({ agent: state.agent, turn: 1 });
  assert.deepEqual(state.selected, codex);
  state.disable('fatfishCodexQuota');
  state.hooks['agent/inbox/claimed']({ agent: state.agent, turn: 2 });
  assert.deepEqual(state.selected, deepSeek);
});

test('Wechat answers explicit model and quota queries and leaves other chat alone', async () => {
  assert.equal(parseWechatServiceQuery('你现在用的是什么模型？'), 'model');
  assert.equal(parseWechatServiceQuery('codex额度、workbuddy积分还有多少'), 'both');
  assert.equal(parseWechatServiceQuery('WorkBuddy 的积分还有多少？'), 'workbuddy');
  assert.equal(parseWechatServiceQuery('告诉我 Codex 本周额度'), 'codex');
  assert.equal(parseWechatServiceQuery('Codex 额度清完再帮我写代码'), undefined);
  assert.equal(parseWechatServiceQuery('随便聊聊天'), undefined);
  assert.equal(parseWechatServiceQuery('切换到 GPT'), 'use-codex');
  assert.equal(parseWechatServiceQuery('切回 DeepSeek'), 'use-deepseek');
  const fetchedAt = Date.now();
  const report = { fetchedAt, remaining: 80, resetsAt: fetchedAt / 1000 + 120,
    weeklyRemaining: 50, weeklyResetsAt: fetchedAt / 1000 + 30 };
  const ctx = { get: key => key === 'fatfishCodexQuota' ? { generation: () => 0, read: async () => report } : undefined };
  assert.equal(await formatWechatQuota(ctx, 'both'),
    'Codex 五小时余 80%，七天余 50%\nWorkBuddy 积分暂时查不到');
});
